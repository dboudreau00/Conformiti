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
}

# Parts an OOXML container only holds if it carries macros. Checked because
# the extension is the uploader's word: renaming evidence.docm to evidence.docx
# defeats a name-only rule, and Office still runs the macros.
MACRO_PARTS = ("vbaproject.bin", "vbadata.xml", "macros/vba")

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
            names = [n.lower() for n in archive.namelist()[:2000]]
    except (zipfile.BadZipFile, OSError, ValueError, AttributeError, NotImplementedError):
        return False
    finally:
        try:
            uploaded.seek(position or 0)
        except (AttributeError, OSError):
            pass
    return any(any(part in name for part in MACRO_PARTS) for name in names)


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
    return uploaded
