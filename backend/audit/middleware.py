"""Records mutating API calls to the audit log. Never breaks the request."""
import ipaddress
import logging

logger = logging.getLogger(__name__)

METHOD_ACTION = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def _client_ip(request):
    """Best-effort client IP as a validated address, or None.

    Behind our nginx, X-Forwarded-For ends with the real client IP the proxy
    appended, so the rightmost hop is the least spoofable choice. The value is
    validated because a header-controlled, malformed IP would otherwise make
    the AuditLog insert fail on databases with a real inet type (e.g. Postgres),
    silently dropping the entry."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    candidate = xff.split(",")[-1].strip() if xff else request.META.get("REMOTE_ADDR")
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except (ValueError, TypeError):
        return None


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._maybe_log(request, response)
        except Exception:  # audit logging must never break the app
            logger.exception("Failed to write audit log entry")
        return response

    def _maybe_log(self, request, response):
        action = METHOD_ACTION.get(request.method)
        user = getattr(request, "user", None)
        if not action or not request.path.startswith("/api/"):
            return
        if "/auth/" in request.path:  # don't log token bodies
            return
        if not (user and user.is_authenticated) or response.status_code >= 400:
            return

        from .models import AuditLog
        ip = _client_ip(request)
        # object_type = the collection segment, e.g. /api/documents/5/ -> documents
        segment = request.path.strip("/").split("/")
        object_type = segment[1] if len(segment) > 1 else ""
        object_id = segment[2] if len(segment) > 2 and segment[2].isdigit() else ""
        AuditLog.objects.create(
            user=user, action=action, object_type=object_type,
            object_id=object_id, detail=request.path, ip_address=ip,
        )
