"""Upload validation shared by every file-accepting endpoint.

nginx caps the request body at the edge; this enforces the same ceiling inside
the application (so the dev server and any direct-to-gunicorn deployment
behave identically) and rejects filenames that would be meaningless or
dangerous on disk. The Django admin takes no file at all (documents/admin.py).
"""
import os
import zipfile

from django.conf import settings
from rest_framework import serializers

# Extensions that browsers will execute or render as active content. Uploads
# are always served with Content-Disposition: attachment, so this is defence
# in depth rather than the primary control, but evidence libraries have no
# legitimate need for these.
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse",
    ".msi", ".scr", ".pif", ".hta", ".jar", ".sh", ".php", ".html", ".htm", ".svg",
    # Web pages in other clothing: .mhtml is a whole page in one file.
    ".mht", ".mhtml", ".xhtml",
    # Macro-enabled Office. An analyst opens these without thinking, which
    # makes them a common malware delivery route. The equivalent formats
    # without macros are accepted, so nothing legitimate is lost: save as
    # .docx, .xlsx or .pptx and upload that.
    ".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".xlsb",
    ".pptm", ".potm", ".ppsm", ".sldm",
    # Legacy Office, which is OLE2 rather than zip, so the macro scan below
    # cannot see inside it: a .doc carries its macros in a stream, and the
    # formats that still get mailed to a compliance inbox are the ones with a
    # decade of memory-corruption history behind them. Blocking only the
    # macro-enabled OOXML names would leave them open.
    ".doc", ".dot", ".xls", ".xlt", ".xla", ".ppt", ".pot", ".pps",
    # RTF is not OLE2 itself, and is the usual wrapper for an object that is.
    ".rtf",
}

# OLE2 / Compound File Binary Format. The extension is the uploader's word, so
# the shape of the file is what decides: this is what a .doc renamed to .dat
# still looks like on disk.
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Parts an OOXML container only holds if it carries macros, or if it carries a
# packaged OLE object, which is the other half of the same trick: the macro
# lives in an embedded binary rather than in the document's own VBA project.
# An embedded worksheet or presentation is a real thing people do, so only the
# packaged-object streams are refused, by suffix.
MACRO_PARTS = ("vbaproject.bin", "vbadata.xml", "macros/vba")
EMBEDDED_OBJECT = "embeddings/"
EMBEDDED_OBJECT_SUFFIXES = (".bin", ".ole", ".emf")

# The macro-free Office formats, which are the ones worth looking inside.
OOXML_EXTENSIONS = {".docx", ".dotx", ".xlsx", ".xltx", ".pptx", ".potx", ".ppsx"}

# OpenDocument is a zip too, and keeps its macros in top-level ``Basic/`` and
# ``Scripts/`` folders (LibreOffice Basic, Python, BeanShell, JavaScript).
ODF_EXTENSIONS = {".odt", ".ott", ".ods", ".ots", ".odp", ".otp", ".odg", ".otg", ".odf", ".odb"}
ODF_SCRIPT_PREFIXES = ("basic/", "scripts/")

# A zip starts with a local-file header, or with the end record when empty.
ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")


# Not covered, deliberately: a macro file one archive level down (a .docm
# inside a .zip, anything inside a .7z or .rar). Looking inside means
# decompressing attacker-chosen containers, which is the ClamAV scan's job
# (documents/scanning.py) rather than something to hand-roll here.
def _holds_macros(uploaded, strict=True):
    """True if this is a zip container with a macro part inside it.

    ``strict`` adds the packaged-object rule (``embeddings/*.bin``). A file
    that only *looks* like a zip, with no Office or OpenDocument name, is
    checked without it: an ordinary archive may hold a folder of that name.

    Unreadable or non-zip files are not this function's business: they are
    not OOXML, and the scanner and the rest of validation still apply.
    """
    try:
        position = uploaded.tell()
    except (AttributeError, OSError):
        position = None
    try:
        uploaded.seek(0)
        with zipfile.ZipFile(uploaded) as archive:
            # Every name, not a prefix. Reading the central directory is what
            # costs, and namelist() has already done it, so a slice would save
            # nothing and leave a place to hide a macro part (entry 2001).
            names = [n.lower() for n in archive.namelist()]
    except (zipfile.BadZipFile, OSError, ValueError, AttributeError, NotImplementedError):
        return False
    finally:
        try:
            uploaded.seek(position or 0)
        except (AttributeError, OSError):
            pass
    if any(any(part in name for part in MACRO_PARTS) for name in names):
        return True
    # An OpenDocument package is recognised by its own members, not its name,
    # so an ordinary archive with a ``scripts/`` folder is left alone.
    is_odf = "mimetype" in names and "meta-inf/manifest.xml" in names
    if is_odf and any(name.startswith(ODF_SCRIPT_PREFIXES) for name in names):
        return True
    return strict and any(EMBEDDED_OBJECT in name and name.endswith(EMBEDDED_OBJECT_SUFFIXES)
               for name in names)


def _is_zip(uploaded):
    """True if the file begins with a zip signature, whatever it is called."""
    try:
        position = uploaded.tell()
    except (AttributeError, OSError):
        position = None
    try:
        uploaded.seek(0)
        head = bytes(uploaded.read(4))
    except (AttributeError, OSError, ValueError):
        return False
    finally:
        try:
            uploaded.seek(position or 0)
        except (AttributeError, OSError):
            pass
    return head.startswith(ZIP_MAGIC)


def _is_ole2(uploaded):
    """True if the file begins with the OLE2 signature, whatever it is called.

    Legacy Office is refused by extension above, and this is the same rule
    applied to the file rather than to its name.
    """
    try:
        position = uploaded.tell()
    except (AttributeError, OSError):
        position = None
    try:
        uploaded.seek(0)
        head = uploaded.read(len(OLE2_MAGIC))
    except (AttributeError, OSError, ValueError):
        return False
    finally:
        try:
            uploaded.seek(position or 0)
        except (AttributeError, OSError):
            pass
    return bool(head) and bytes(head).startswith(OLE2_MAGIC)


def validate_upload(uploaded):
    """Raise serializers.ValidationError if the file is too large or of a
    blocked type. Returns the file unchanged otherwise."""
    if uploaded is None:
        return uploaded
    size = getattr(uploaded, "size", None)
    if size is not None and size > settings.MAX_UPLOAD_BYTES:
        raise serializers.ValidationError(
            f"File is larger than the {settings.MAX_UPLOAD_MB} MB upload limit."
        )
    if size == 0:
        raise serializers.ValidationError("The uploaded file is empty.")
    name = getattr(uploaded, "name", "") or ""
    base = os.path.basename(name.replace("\\", "/"))
    if not base or base in (".", ".."):
        raise serializers.ValidationError("The uploaded file has no usable name.")
    ext = os.path.splitext(base)[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        raise serializers.ValidationError(
            f"{ext} files cannot be stored as evidence. Export the content to PDF or "
            "an archive and upload that instead."
        )
    # By name for the Office and OpenDocument formats, and by shape for
    # anything else: a macro document renamed to .zip or .dat is still one.
    named_office = ext in OOXML_EXTENSIONS or ext in ODF_EXTENSIONS
    if (named_office or _is_zip(uploaded)) and _holds_macros(uploaded, strict=named_office):
        raise serializers.ValidationError(
            "That file carries macros, whatever its name says. Remove them, or save "
            "it as PDF, and upload that instead."
        )
    if _is_ole2(uploaded):
        raise serializers.ValidationError(
            "That is a legacy Office file, whatever it is called. Save it as PDF, "
            "or in the modern format (.docx, .xlsx, .pptx), and upload that instead."
        )
    return uploaded
