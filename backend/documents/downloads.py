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
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse, Http404


def _content_disposition(filename):
    """RFC 6266 ``attachment`` with an ASCII fallback.

    Always an attachment: an uploaded .html or .svg served inline would run as
    stored XSS in the application's own origin.
    """
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "download"
    ascii_name = ascii_name.replace('"', "").replace("\\", "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def serve_stored_file(file_field, download_name=None):
    """Return a response streaming ``file_field``'s bytes to an authorised caller.

    With ``MEDIA_INTERNAL`` (the default off DEBUG) the response is empty and
    carries ``X-Accel-Redirect``, which nginx expands into a send from its own
    ``internal`` location — the client never learns the storage path, and a
    direct request for it is refused. Without it (the dev server, or a
    deployment with no accelerator) the file is streamed by Django.
    """
    if not file_field:
        raise Http404("This document has no file.")
    name = download_name or posixpath.basename(file_field.name)

    if getattr(settings, "USE_S3", False):
        # Object storage signs its own time-limited URLs; there is nothing on
        # local disk for nginx to send.
        response = FileResponse(file_field.open("rb"), as_attachment=True, filename=name)
    elif getattr(settings, "MEDIA_INTERNAL", False):
        response = HttpResponse(status=200)
        # The stored name is relative to MEDIA_ROOT and may contain spaces and
        # non-ASCII; nginx wants it percent-encoded.
        internal = settings.MEDIA_ACCEL_PREFIX + quote(file_field.name.replace(os.sep, "/"))
        response["X-Accel-Redirect"] = internal
        # Let nginx pick the length; clearing the type makes it sniff from the
        # file, which we then override below.
        del response["Content-Type"]
        response["Content-Type"] = mimetypes.guess_type(name)[0] or "application/octet-stream"
    else:
        response = FileResponse(file_field.open("rb"), filename=name)

    response["Content-Disposition"] = _content_disposition(name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Referrer-Policy"] = "same-origin"
    # Evidence is not public, and a shared cache must not keep a copy.
    response["Cache-Control"] = "private, no-store"
    return response
