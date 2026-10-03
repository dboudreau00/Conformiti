"""Records mutating API calls to the audit log. Never breaks the request."""
import ipaddress
import json
import logging

logger = logging.getLogger(__name__)

METHOD_ACTION = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}

# Paths whose writes are per-user UI state, not compliance events, or which
# carry credentials. They are never written to the trail by this middleware
# (authentication events are recorded explicitly, see audit/events.py).
SKIP_PREFIXES = ("/api/auth/", "/api/notifications/", "/api/health/")

# Request-body keys that must never appear in the trail, even as field names
# with no values. (Values are never recorded regardless.)
SENSITIVE_KEYS = {"password", "current_password", "new_password", "api_token", "otp", "code", "secret"}

MAX_BODY_CAPTURE = 64 * 1024   # bytes: bigger bodies (uploads) are not inspected
MAX_DETAIL = 255               # AuditLog.detail column width

# The Django admin writes to the same tables the API does, so its saves are
# recorded too. Sign-in is recorded by the admin's own form, and a password
# set on the admin's password page as its own event.
ADMIN_PREFIX = "/admin/"
ADMIN_FORM_NOISE = {"csrfmiddlewaretoken", "password1", "password2"}


def _admin_target(request):
    """(action, object_type, object_id) for a Django admin save, or None for
    a page that is not one: add, change, delete, or a bulk action on a list."""
    parts = request.path[len(ADMIN_PREFIX):].strip("/").split("/")
    if len(parts) < 2 or not all(parts[:2]):
        return None
    rest = parts[2:]
    if rest == ["add"]:
        action, pk = "create", ""
    elif len(rest) == 2 and rest[1] in ("change", "delete"):
        action, pk = ("update" if rest[1] == "change" else "delete"), rest[0]
    elif not rest:
        action, pk = ("delete" if request.POST.get("action") == "delete_selected" else "update"), ""
    else:
        return None  # history, the password page, and anything else
    return action, f"admin:{parts[0]}.{parts[1]}", pk


def _client_ip(request):
    """Best-effort client IP as a validated address, or None.

    The address NUM_PROXIES hops back along X-Forwarded-For, chosen exactly as
    the rate limits choose it (DRF's get_ident): each proxy in front appends
    the address it received from, so the client is that many entries from the
    right, and entries further left are whatever the client sent. Taking the
    rightmost entry regardless of NUM_PROXIES would record the terminator for
    every client behind one in front of the shipped nginx. The value is
    validated because a header-controlled, malformed IP would otherwise make
    the AuditLog insert fail on databases with a real inet type (e.g.
    Postgres), dropping the entry."""
    from rest_framework.settings import api_settings

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    remote = request.META.get("REMOTE_ADDR")
    proxies = api_settings.NUM_PROXIES
    if proxies is None:
        candidate = xff.split(",")[-1].strip() if xff else remote
    elif proxies == 0 or not xff:
        candidate = remote
    else:
        hops = xff.split(",")
        candidate = hops[-min(proxies, len(hops))].strip()
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except (ValueError, TypeError):
        return None


def _summarise_body(request):
    """Return the *names* of the top-level fields in a JSON or form body, so
    an entry reads 'PATCH /api/users/3/ fields=role,is_active' rather than
    just the path. Values are deliberately not recorded: the trail must be
    safe to hand to an auditor without leaking document text or secrets."""
    if request.method not in ("POST", "PUT", "PATCH"):
        return ""
    ctype = (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
    keys = []
    try:
        if ctype == "application/json":
            length = int(request.META.get("CONTENT_LENGTH") or 0)
            if 0 < length <= MAX_BODY_CAPTURE:
                # Reading .body here caches it on the request, so DRF's parser
                # still sees the full stream afterwards.
                payload = json.loads(request.body.decode("utf-8") or "null")
                if isinstance(payload, dict):
                    keys = list(payload.keys())
        elif ctype in ("application/x-www-form-urlencoded", "multipart/form-data"):
            keys = list(request.POST.keys()) + list(request.FILES.keys())
    except Exception:  # malformed body: the view will reject it, so there is nothing to record
        return ""
    keys = [k for k in keys if k not in SENSITIVE_KEYS][:20]
    return ",".join(keys)


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        fields = ""
        admin_save = request.method == "POST" and request.path.startswith(ADMIN_PREFIX)
        if (request.method in METHOD_ACTION and request.path.startswith("/api/")
                and not request.path.startswith(SKIP_PREFIXES)) or admin_save:
            try:
                fields = _summarise_body(request)
            except Exception:
                fields = ""
        response = self.get_response(request)
        try:
            if admin_save:
                self._maybe_log_admin(request, response, fields)
            else:
                self._maybe_log(request, response, fields)
        except Exception:  # audit logging must never break the app
            logger.exception("Failed to write audit log entry")
        return response

    def _maybe_log_admin(self, request, response, fields):
        """A Django admin save: a POST the admin answered with a redirect,
        which it does only once a form is saved (a refused one re-renders)."""
        user = getattr(request, "user", None)
        if response.status_code != 302 or not (user and user.is_authenticated):
            return
        target = _admin_target(request)
        if target is None:
            return
        action, object_type, object_id = target

        from .models import AuditLog
        names = [f for f in fields.split(",") if f and f not in ADMIN_FORM_NOISE
                 and not f.startswith("_")] if fields else []
        detail = f"admin {request.method} {request.path}"
        selected = request.POST.getlist("_selected_action")
        if selected:
            detail += f" {request.POST.get('action', '')} rows={len(selected)}"
        if names:
            detail += f" fields={','.join(names)}"
        AuditLog.objects.create(
            user=user, action=action, object_type=object_type[:80],
            object_id=object_id[:80], detail=detail[:MAX_DETAIL], ip_address=_client_ip(request),
        )

    def _maybe_log(self, request, response, fields):
        action = METHOD_ACTION.get(request.method)
        user = getattr(request, "user", None)
        if not action or not request.path.startswith("/api/"):
            return
        if request.path.startswith(SKIP_PREFIXES):
            return
        if not (user and user.is_authenticated) or response.status_code >= 400:
            return

        from .models import AuditLog
        ip = _client_ip(request)
        # object_type = the collection segment, e.g. /api/documents/5/ -> documents
        segment = request.path.strip("/").split("/")
        object_type = segment[1] if len(segment) > 1 else ""
        object_id = segment[2] if len(segment) > 2 and segment[2].isdigit() else ""
        # For a create, the new record's id is in the response body, not the URL.
        if not object_id and action == "create":
            data = getattr(response, "data", None)
            if isinstance(data, dict) and isinstance(data.get("id"), int):
                object_id = str(data["id"])
        detail = f"{request.method} {request.path}"
        if fields:
            detail += f" fields={fields}"
        AuditLog.objects.create(
            user=user, action=action, object_type=object_type[:80],
            object_id=object_id[:80], detail=detail[:MAX_DETAIL], ip_address=ip,
        )
