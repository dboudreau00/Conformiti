"""Upload validation shared by every file-accepting endpoint.

nginx caps the request body at the edge; this enforces the same ceiling inside
the application (so the dev server, the admin and any direct-to-gunicorn
deployment behave identically) and rejects filenames that would be
meaningless or dangerous on disk.
"""
import os
import zipfile

from django.conf import settings
from rest_framework import serializers

# Extensions that browsers will execute or render as active content. Uploads
# are always served with Content-Disposition: attachment, so this is defence
# in depth rather than the primary control — but evidence libraries have no
# legitimate need for these.
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse",
    ".msi", ".scr", ".pif", ".hta", ".jar", ".sh", ".php", ".html", ".htm", ".svg",
    # Web pages in other clothing: .mhtml is a whole page in one file.
    ".mht", ".mhtml", ".xhtml",
    # Macro-enabled Office. These are the files an analyst opens without
    # thinking, which is what makes them the delivery method of choice. The
    # equivalent formats without macros are accepted, so nothing legitimate
    # is lost: save as .docx, .xlsx or .pptx and upload that.
    ".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".xlsb",
    ".pptm", ".potm", ".ppsm", ".sldm",
    # Legacy Office, which is OLE2 rather than zip, so the macro scan below
    # cannot see inside it: a .doc carries its macros in a stream, and the
    # formats that still get mailed to a compliance inbox are exactly the ones
    # with a decade of memory-corruption history behind them. Blocking the
    # macro-enabled OOXML names while accepting .doc was half a rule.
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


def _holds_macros(uploaded):
    """True if this is a zip container with a macro part inside it.

    Unreadable or non-zip files are not this function's business: they are
    simply not OOXML, and the scanner and the rest of validation still apply.
    """
    try:
        position = uploaded.tell()
    except (AttributeError, OSError):
        position = None
    try:
        uploaded.seek(0)
        with zipfile.ZipFile(uploaded) as archive:
            # Every name, not the first two thousand. Reading the central
            # directory is what costs, and namelist() has already done it, so
            # the old slice bought nothing and left a place to hide a macro
            # part: entry 2001.
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
    return any(EMBEDDED_OBJECT in name and name.endswith(EMBEDDED_OBJECT_SUFFIXES)
               for name in names)


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
    if ext in OOXML_EXTENSIONS and _holds_macros(uploaded):
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
