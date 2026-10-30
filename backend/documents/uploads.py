"""Upload validation for every file-accepting endpoint; enforces the size ceiling nginx also applies at the edge."""
import os
import zipfile

from django.conf import settings
from rest_framework import serializers

# Active-content and macro-bearing formats. Uploads are always served as attachments, so this is defence in depth.
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse",
    ".msi", ".scr", ".pif", ".hta", ".jar", ".sh", ".php", ".html", ".htm", ".svg",
    # .mhtml is a whole web page in one file.
    ".mht", ".mhtml", ".xhtml",
    # Macro-enabled Office, a common malware route; the macro-free equivalents are accepted.
    ".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".xlsb",
    ".pptm", ".potm", ".ppsm", ".sldm",
    # Legacy Office is OLE2, not zip, so the macro scan cannot see inside it: refused by name here, by signature below.
    ".doc", ".dot", ".xls", ".xlt", ".xla", ".ppt", ".pot", ".pps",
    # RTF is the usual wrapper for an OLE2 object.
    ".rtf",
}

# OLE2 / Compound File signature: the extension is the uploader's word, so the file's own shape decides.
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Parts only a macro-bearing OOXML container holds, plus packaged OLE objects (a macro can hide in an embedded binary).
# Embedded worksheets and presentations are legitimate, so only the packaged-object streams are refused, by suffix.
MACRO_PARTS = ("vbaproject.bin", "vbadata.xml", "macros/vba")
EMBEDDED_OBJECT = "embeddings/"
EMBEDDED_OBJECT_SUFFIXES = (".bin", ".ole", ".emf")

OOXML_EXTENSIONS = {".docx", ".dotx", ".xlsx", ".xltx", ".pptx", ".potx", ".ppsx"}

# OpenDocument is a zip too; its macros live in top-level ``Basic/`` and ``Scripts/`` folders.
ODF_EXTENSIONS = {".odt", ".ott", ".ods", ".ots", ".odp", ".otp", ".odg", ".otg", ".odf", ".odb"}
ODF_SCRIPT_PREFIXES = ("basic/", "scripts/")

# Not covered on purpose: macro files one archive level down (a .docm inside a .zip, anything in a .7z or .rar).
# Decompressing attacker-chosen containers is the ClamAV scan's job (scanning.py), not something to hand-roll here.
def _zip_names(uploaded):
    """Lower-cased member names of a zip, or None when it is not one.
    zipfile decides, from the end of the file as Office does: bytes in front of the archive do not hide it."""
    try:
        position = uploaded.tell()
    except (AttributeError, OSError):
        position = None
    try:
        uploaded.seek(0)
        with zipfile.ZipFile(uploaded) as archive:
            # Every name, not a prefix: the directory is already read, and a slice would leave room to hide a macro.
            return [n.lower() for n in archive.namelist()]
    except (zipfile.BadZipFile, OSError, ValueError, AttributeError, NotImplementedError):
        return None
    finally:
        try:
            uploaded.seek(position or 0)
        except (AttributeError, OSError):
            pass


def _is_macro_part(name):
    """Macro part by whole path segments, so a folder that merely mentions macros is left alone."""
    parts = name.split("/")
    if parts[-1] in ("vbaproject.bin", "vbadata.xml"):
        return True
    return any(parts[i] == "macros" and parts[i + 1] == "vba" for i in range(len(parts) - 1))


def _holds_macros(uploaded, named=False, odf=False):
    """True if a zip holds a macro part. ``named``/``odf`` say its name is Office/OpenDocument: those get the strict
    rules (substring match, packaged objects); any other zip is judged by whole path segments only."""
    names = _zip_names(uploaded)
    if names is None:
        return False
    if named:
        found = any(any(part in name for part in MACRO_PARTS) for name in names)
    else:
        found = any(_is_macro_part(name) for name in names)
    if found:
        return True
    # OpenDocument is recognised by name or by its own members: an .odt is not let through for lacking ``mimetype``,
    # and an ordinary archive with a ``scripts/`` folder is left alone.
    is_odf = odf or ("mimetype" in names and "meta-inf/manifest.xml" in names)
    if is_odf and any(name.startswith(ODF_SCRIPT_PREFIXES) for name in names):
        return True
    return named and any(EMBEDDED_OBJECT in name and name.endswith(EMBEDDED_OBJECT_SUFFIXES)
                         for name in names)


def _is_ole2(uploaded):
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
    """Raise ``ValidationError`` if the file is refused; return it unchanged otherwise."""
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
    # By name for Office and OpenDocument, by shape for anything else: a macro file renamed to .dat is still one.
    named_odf = ext in ODF_EXTENSIONS
    named_office = ext in OOXML_EXTENSIONS or named_odf
    if _holds_macros(uploaded, named=named_office, odf=named_odf):
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
