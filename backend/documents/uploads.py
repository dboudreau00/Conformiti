"""Upload validation shared by every file-accepting endpoint.

nginx caps the request body at the edge; this enforces the same ceiling inside
the application (so the dev server, the admin and any direct-to-gunicorn
deployment behave identically) and rejects filenames that would be
meaningless or dangerous on disk.
"""
import os

from django.conf import settings
from rest_framework import serializers

# Extensions that browsers will execute or render as active content. Uploads
# are always served with Content-Disposition: attachment, so this is defence
# in depth rather than the primary control — but evidence libraries have no
# legitimate need for these.
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse",
    ".msi", ".scr", ".pif", ".hta", ".jar", ".sh", ".php", ".html", ".htm", ".svg",
}


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
    return uploaded
