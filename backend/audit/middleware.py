"""Records mutating API calls to the audit log. Never breaks the request."""
import ipaddress
import json
import logging

logger = logging.getLogger(__name__)

METHOD_ACTION = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}

# UI-state and credential-bearing paths are never recorded here; auth events are written explicitly by events.py.
SKIP_PREFIXES = ("/api/auth/", "/api/notifications/", "/api/health/")

# Field names that must never appear in the trail, even without their values.
SENSITIVE_KEYS = {"password", "current_password", "new_password", "api_token", "otp", "code", "secret"}

MAX_BODY_CAPTURE = 64 * 1024   # bytes: bigger bodies (uploads) are not inspected
MAX_DETAIL = 255               # AuditLog.detail column width

# Admin saves are recorded like API writes; sign-in and the password page have their own events.
ADMIN_PREFIX = "/admin/"
ADMIN_FORM_NOISE = {"csrfmiddlewaretoken", "password1", "password2"}


def _admin_target(request):
    """(action, object_type, object_id) for an admin save (add, change, delete, bulk action), else None."""
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
    """Best-effort client IP or None, chosen as DRF's get_ident chooses it: NUM_PROXIES hops back in X-Forwarded-For.
    Validated, because a malformed header value would make the insert fail on databases with an inet type."""
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


def _summarise_body(request, form=False):
    """Names, never values, of the top-level fields of a JSON or form body: the trail is handed to auditors.
    JSON is read before the view (capped); a form or upload after it (``form``), so refused callers cost no parsing."""
    if request.method not in ("POST", "PUT", "PATCH"):
        return ""
    ctype = (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
    keys = []
    try:
        if ctype == "application/json" and not form:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
            if 0 < length <= MAX_BODY_CAPTURE:
                # Reading .body caches it on the request, so DRF's parser still sees the full stream.
                payload = json.loads(request.body.decode("utf-8") or "null")
                if isinstance(payload, dict):
                    keys = list(payload.keys())
        elif ctype in ("application/x-www-form-urlencoded", "multipart/form-data") and form:
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
        """An admin save: a POST the admin answers with a redirect, which it does only once a form is saved."""
        user = getattr(request, "user", None)
        if response.status_code != 302 or not (user and user.is_authenticated):
            return
        target = _admin_target(request)
        if target is None:
            return
        action, object_type, object_id = target
        fields = fields or _summarise_body(request, form=True)

        from .models import AuditLog
        names = [f for f in fields.split(",") if f and f not in ADMIN_FORM_NOISE and not f.startswith("_")]
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
        fields = fields or _summarise_body(request, form=True)

        from .models import AuditLog
        ip = _client_ip(request)
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
