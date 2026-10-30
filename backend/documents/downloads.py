"""Serves stored files through the application so every read is authorised and audited: nginx does not serve the media
volume directly (upload paths are predictable) and is handed the bytes with ``X-Accel-Redirect``."""
import mimetypes
import os
import posixpath
import unicodedata
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse, Http404

# As FileResponse does: a compressed file is typed by its compression, since no Content-Encoding is sent.
_ENCODING_TYPES = {
    "br": "application/x-brotli",
    "bzip2": "application/x-bzip",
    "compress": "application/x-compress",
    "gzip": "application/gzip",
    "xz": "application/x-xz",
}


def _extension(filename):
    """The extension of ``filename``, both parts of a compressed tarball (splitext would give only ".gz")."""
    stem, ext = posixpath.splitext(filename)
    if ext and posixpath.splitext(stem)[1].lower() == ".tar" and (
            ext in mimetypes.encodings_map or ext.lower() in mimetypes.encodings_map):
        return filename[len(posixpath.splitext(stem)[0]):]
    return ext


def download_filename(name, stored_name, tag=""):
    """``name`` + ``tag`` + the stored file's extension. Display names are usually typed without one; a name that
    already ends in it is not given a second, and ``tag`` (" (v2)") goes before it."""
    stored = posixpath.basename(str(stored_name or "").replace("\\", "/"))
    ext = _extension(stored)
    name = str(name or "").strip() or stored[: len(stored) - len(ext)] or "download"
    # "Backup.tar" for a stored .tar.gz becomes "Backup.tar.gz", not "Backup.tar.tar.gz".
    for tail in (ext, *posixpath.splitext(ext)):
        if tail and name.lower().endswith(tail.lower()):
            name = name[: -len(tail)] or "download"
            break
    return f"{name}{tag}{ext}"


def _content_type(filename):
    content_type, encoding = mimetypes.guess_type(filename)
    return _ENCODING_TYPES.get(encoding, content_type) or "application/octet-stream"


def _content_disposition(filename, disposition="attachment"):
    """RFC 6266 header with an ASCII fallback and an RFC 5987 ``filename*`` that carries the name exactly. Downloads are
    attachments: an uploaded .html or .svg served inline would run as stored XSS in the application's origin."""
    def ascii_only(text):
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        return "".join(c for c in text if c.isprintable() and c not in '"\\').strip()

    # Accented letters fall back to their plain form, not to nothing; a name with no ASCII left keeps its extension.
    ascii_name = ascii_only(filename)
    ext = ascii_only(_extension(filename))
    ext = ext if ext.strip(".") else ""
    if not ascii_name.strip(".") or ascii_name == ext:
        ascii_name = "download" + ext
    # safe='' because quote() leaves "/" alone by default and it is not an RFC 5987 attr-char.
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def serve_stored_file(file_field, download_name=None):
    """Response for an authorised caller. With ``MEDIA_INTERNAL`` the body is empty and nginx sends the file from its
    internal location, so the client never learns the storage path; otherwise the file is streamed from here."""
    if not file_field:
        raise Http404("This document has no file.")
    name = download_filename(download_name, file_field.name)
    content_type = _content_type(name)

    if getattr(settings, "USE_S3", False):
        # Object storage: there is nothing on local disk for nginx to send.
        response = FileResponse(file_field.open("rb"), as_attachment=True, filename=name,
                                content_type=content_type)
    elif getattr(settings, "MEDIA_INTERNAL", False):
        response = HttpResponse(status=200)
        internal = settings.MEDIA_ACCEL_PREFIX + quote(file_field.name.replace(os.sep, "/"))
        response["X-Accel-Redirect"] = internal
        # nginx picks the length; the default type is cleared so it sniffs the file, and the type set below wins.
        del response["Content-Type"]
        response["Content-Type"] = content_type
    else:
        response = FileResponse(file_field.open("rb"), filename=name, content_type=content_type)

    response["Content-Disposition"] = _content_disposition(name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Referrer-Policy"] = "same-origin"
    response["Cache-Control"] = "private, no-store"
    return response


def serve_inline(file_field, content_type, download_name=None):
    """Stream a file inline. Call only for a kind ``preview.render`` verified from the file's own bytes (PDF, image)."""
    if not file_field:
        raise Http404("This document has no file.")
    name = download_filename(download_name, file_field.name)
    if getattr(settings, "MEDIA_INTERNAL", False) and not getattr(settings, "USE_S3", False):
        response = HttpResponse(status=200)
        response["X-Accel-Redirect"] = settings.MEDIA_ACCEL_PREFIX + quote(
            file_field.name.replace(os.sep, "/"))
        del response["Content-Type"]
    else:
        response = FileResponse(file_field.open("rb"))
    response["Content-Type"] = content_type
    response["Content-Disposition"] = _content_disposition(name, "inline")
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        "frame-ancestors 'self'; object-src 'none'; script-src 'none'"
    )
    response["Referrer-Policy"] = "same-origin"
    response["Cache-Control"] = "private, no-store"
    return response
