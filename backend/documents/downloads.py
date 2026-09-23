"""
Serving stored files through the application, so that reading evidence is an
authorised, auditable act.

Until 0.3.0 the shipped nginx served the whole media volume directly. Upload
paths are derived from the folder tree and the file name
(``documents/<framework>/<category>/<control>/<file>``), so anyone who could
reach the site and guess or observe a path could fetch any document regardless
of its folder permissions — and nothing recorded that they had.

Every read now goes through a view that has already resolved the caller's
rights. The bytes themselves are still handed to nginx to send (``X-Accel-
Redirect``), so authorisation costs a Python call and the transfer does not.
"""
import mimetypes
import os
import posixpath
import unicodedata
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse, Http404

# FileResponse's own mapping for a compressed file: the type names the
# compression (application/gzip for a .tar.gz), not what is inside, because
# no Content-Encoding is sent and the bytes are the compressed ones.
_ENCODING_TYPES = {
    "br": "application/x-brotli",
    "bzip2": "application/x-bzip",
    "compress": "application/x-compress",
    "gzip": "application/gzip",
    "xz": "application/x-xz",
}


def _extension(filename):
    """``filename``'s extension, both parts of it for a compressed tarball.

    posixpath.splitext takes only the last suffix, so "logs.tar.gz" gave
    ".gz" and a document named "Backup logs" downloaded as "Backup logs.gz",
    which decompresses to an extensionless tar. A ".tar" followed by a
    compression suffix mimetypes knows (.gz, .bz2, .xz, .Z, .br) is kept
    whole. Django's storage keeps every suffix when it renames a clashing
    upload ("logs_Ab12cde.tar.gz"), so the stored name still ends in both.
    """
    stem, ext = posixpath.splitext(filename)
    if ext and posixpath.splitext(stem)[1].lower() == ".tar" and (
            ext in mimetypes.encodings_map or ext.lower() in mimetypes.encodings_map):
        return filename[len(posixpath.splitext(stem)[0]):]
    return ext


def download_filename(name, stored_name, tag=""):
    """The name a stored file is saved under: ``name``, then ``tag``, then the
    stored file's extension.

    ``name`` is usually a document's display name, which people type without
    an extension ("Access Control Policy"). Sent as it was, the download had
    no extension, the OS could not open it, and its type was guessed from a
    name with nothing to guess from. The stored file keeps the extension it
    was uploaded with, so that is the one the download carries; a display
    name that already ends in it is not given a second. ``tag`` (" (v2)")
    goes before the extension, all of it for a ".tar.gz".
    """
    stored = posixpath.basename(str(stored_name or "").replace("\\", "/"))
    ext = _extension(stored)
    name = str(name or "").strip() or stored[: len(stored) - len(ext)] or "download"
    # "Backup.tar" or "Backup.gz" for a stored .tar.gz ends in one part of the
    # extension, and is "Backup.tar.gz", not "Backup.tar.tar.gz" or
    # "Backup.gz.tar.gz".
    for tail in (ext, *posixpath.splitext(ext)):
        if tail and name.lower().endswith(tail.lower()):
            name = name[: -len(tail)] or "download"
            break
    return f"{name}{tag}{ext}"


def _content_type(filename):
    """The type for a download, from its name's extension (which
    ``download_filename`` takes from the stored file); octet-stream only when
    the extension is unknown."""
    content_type, encoding = mimetypes.guess_type(filename)
    return _ENCODING_TYPES.get(encoding, content_type) or "application/octet-stream"


def _content_disposition(filename, disposition="attachment"):
    """RFC 6266 ``attachment`` with an ASCII fallback and an RFC 5987
    ``filename*`` that carries the name exactly, non-ASCII included.

    Always an attachment for a download: an uploaded .html or .svg served
    inline would run as stored XSS in the application's own origin.
    """
    def ascii_only(text):
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        return "".join(c for c in text if c.isprintable() and c not in '"\\').strip()

    # "Politique de sécurité.pdf" falls back to "Politique de securite.pdf",
    # not "Politique de scurit.pdf"; a name with no ASCII left keeps its
    # extension ("download.pdf").
    ascii_name = ascii_only(filename)
    ext = ascii_only(_extension(filename))
    ext = ext if ext.strip(".") else ""
    if not ascii_name.strip(".") or ascii_name == ext:
        ascii_name = "download" + ext
    # quote() leaves "/" alone by default, and "/" is not an RFC 5987
    # attr-char, so nothing is exempt here.
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def serve_stored_file(file_field, download_name=None):
    """Return a response streaming ``file_field``'s bytes to an authorised caller.

    With ``MEDIA_INTERNAL`` (the default off DEBUG) the response is empty and
    carries ``X-Accel-Redirect``, which nginx expands into a send from its own
    ``internal`` location — the client never learns the storage path, and a
    direct request for it is refused. Without it (the dev server, or a
    deployment with no accelerator) the file is streamed by Django.

    The download is named by ``download_filename`` (the display name plus the
    stored file's extension) and typed from that extension on every branch.
    """
    if not file_field:
        raise Http404("This document has no file.")
    name = download_filename(download_name, file_field.name)
    content_type = _content_type(name)

    if getattr(settings, "USE_S3", False):
        # Object storage signs its own time-limited URLs; there is nothing on
        # local disk for nginx to send.
        response = FileResponse(file_field.open("rb"), as_attachment=True, filename=name,
                                content_type=content_type)
    elif getattr(settings, "MEDIA_INTERNAL", False):
        response = HttpResponse(status=200)
        # The stored name is relative to MEDIA_ROOT and may contain spaces and
        # non-ASCII; nginx wants it percent-encoded.
        internal = settings.MEDIA_ACCEL_PREFIX + quote(file_field.name.replace(os.sep, "/"))
        response["X-Accel-Redirect"] = internal
        # Let nginx pick the length; clearing the type makes it sniff from the
        # file, which we then override below.
        del response["Content-Type"]
        response["Content-Type"] = content_type
    else:
        response = FileResponse(file_field.open("rb"), filename=name, content_type=content_type)

    response["Content-Disposition"] = _content_disposition(name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Referrer-Policy"] = "same-origin"
    # Evidence is not public, and a shared cache must not keep a copy.
    response["Cache-Control"] = "private, no-store"
    return response


def serve_inline(file_field, content_type, download_name=None):
    """Stream a file for display *inside* the app, not as an attachment.

    Only ever called for a kind the preview module has verified from the
    file's own bytes -- a PDF that starts with %PDF-, an image with its magic
    number. The CSP still forbids scripts and plugins, and frame-ancestors is
    restricted to the app itself, so the document can be shown in the viewer
    and nowhere else.
    """
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
