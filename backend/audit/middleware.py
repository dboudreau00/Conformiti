"""Records mutating API calls to the audit log. Never breaks the request."""
import ipaddress
import json
import logging

logger = logging.getLogger(__name__)

METHOD_ACTION = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}
VERBS = {"create": "created", "update": "changed", "delete": "deleted"}

# What a person calls the record behind an API path (the part after /api/). A path not listed here, such as an add-on's,
# keeps the raw call as its detail rather than a guess.
RESOURCE_NOUN = {
    "access-review-items": "access review item", "access-reviews": "access review",
    "calendar": "calendar event", "champion-groups": "champion group", "control-evidence": "evidence link",
    "controls": "control", "crosswalk": "crosswalk mapping", "documents": "document",
    "evidence-packages": "audit package", "folder-permissions": "folder permission", "folders": "folder",
    "form-templates": "form template", "frameworks": "framework", "group-members": "group member",
    "integrations/jira/boards": "Jira board", "meeting-minutes": "meeting minutes",
    "meeting-series": "meeting series", "package-controls": "package control",
    "package-evidence": "package document", "package-grants": "package grant", "package-samples": "package sample",
    "pbc-items": "request item", "pbc-requests": "auditor request", "questionnaire-invites": "questionnaire invitation",
    "responsibilities": "responsibility", "risk-notes": "risk note", "risks": "risk", "roles": "role",
    "users": "member", "vendor-assessments": "vendor assessment", "vendors": "vendor", "workspaces": "workspace",
}
# Calls that are not the creation, change or deletion of one record.
FIXED_PHRASE = {
    "integrations/jira/config": "changed the Jira settings",
    "integrations/jira/test": "tested the Jira connection",
}
FIELD_WORDS = {"is_active": "active status", "is_superuser": "administrator status", "is_staff": "staff status"}

# UI-state and credential-bearing paths are never recorded here; auth events are written explicitly by events.py.
SKIP_PREFIXES = ("/api/auth/", "/api/notifications/", "/api/health/")

# Field names that must never appear in the trail, even without their values.
SENSITIVE_KEYS = {"password", "current_password", "new_password", "api_token", "otp", "code", "secret"}

MAX_BODY_CAPTURE = 64 * 1024   # bytes: a bigger JSON body is not parsed ahead of the view; the view's parse is read
MAX_DETAIL = 255               # AuditLog.detail column width
MAX_NAME = 40                  # a field name longer than this is cut, so one key cannot use up the width

# Named first when the list is too long for the column: a change to who may do what must not be the name that is
# left out.
PRIVILEGED_KEYS = ("role", "is_active", "is_superuser", "is_staff", "workspace", "access_level", "user", "group")

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
    return _names(keys)


def _names(keys):
    """The field names as one comma-separated string: no sensitive name, privileged ones first, each cut to MAX_NAME."""
    keys = [str(k) for k in keys if k not in SENSITIVE_KEYS]
    keys.sort(key=lambda k: k not in PRIVILEGED_KEYS)   # stable: the rest keep the order they were sent in
    return ",".join(k.replace(",", " ")[:MAX_NAME] for k in keys)


def _applied_names(response):
    """The names of a JSON body too big to read ahead of the view, through DRF's parse. Called only for an entry that is
    written (a signed-in call that succeeded), so a refused or anonymous body is still never parsed for the trail."""
    request = (getattr(response, "renderer_context", None) or {}).get("request")
    if request is None:
        return ""
    # The media type alone: a parameter such as "; charset=utf-8" must not hide the names.
    if (request.content_type or "").split(";")[0].strip().lower() != "application/json":
        return ""
    try:
        data = request.data
    except Exception:
        return ""
    return _names(data.keys()) if isinstance(data, dict) else ""


def _phrase(action, segment, object_id):
    """A short sentence for an API write on a known record type ("created vendor 12", "seal on audit package 3"),
    else None."""
    path = "/".join(segment[1:])
    for key, text in FIXED_PHRASE.items():
        if path == key or path.startswith(key + "/"):
            return text
    key = max((k for k in RESOURCE_NOUN if path == k or path.startswith(k + "/")), key=len, default=None)
    if key is None:
        return None
    rest = [s for s in path[len(key):].split("/") if s]
    ident = rest.pop(0) if rest and rest[0].isdigit() else object_id
    target = f"{RESOURCE_NOUN[key]} {ident}" if ident else RESOURCE_NOUN[key]
    steps = " ".join(s.replace("_", " ").replace("-", " ") for s in rest if not s.isdigit())
    return f"{steps} on {target}" if steps else f"{VERBS[action]} {target}"


def _join(names):
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _detail(base, fields):
    """``base`` plus ", set" and the field names in words, within MAX_DETAIL. Names that do not fit are counted."""
    names = [FIELD_WORDS.get(n) or n.replace("_", " ") for n in fields.split(",") if n]
    if not names:
        return base[:MAX_DETAIL]
    head = f"{base}, set "
    kept = []
    for i, name in enumerate(names):
        more = len(names) - i - 1
        tail = f" and {more} more" if more else ""
        if len(head) + len(", ".join(kept + [name])) + len(tail) > MAX_DETAIL:
            break
        kept.append(name)
    left = len(names) - len(kept)
    if left and not kept:
        return (head + f"{left} fields")[:MAX_DETAIL]
    return (head + _join(kept + ([f"{left} more"] if left else [])))[:MAX_DETAIL]


def _call_detail(base, fields):
    """``base`` plus the field names as sent, within MAX_DETAIL: the record of a call whose path this module cannot
    put in words. Names that do not fit are counted, never dropped silently."""
    names = [n for n in fields.split(",") if n]
    if not names:
        return base[:MAX_DETAIL]
    head = f"{base} fields="
    kept = []
    for i, name in enumerate(names):
        more = len(names) - i - 1
        tail = f",+{more} more" if more else ""
        if len(head) + len(",".join(kept + [name])) + len(tail) > MAX_DETAIL:
            break
        kept.append(name)
    left = len(names) - len(kept)
    if left:
        kept.append(f"+{left} more")
    return (head + ",".join(kept))[:MAX_DETAIL]


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
        model = object_type.rsplit(".", 1)[-1].replace("_", " ")
        selected = request.POST.getlist("_selected_action")
        if selected:
            chosen = request.POST.get("action", "").replace("_", " ")
            detail = f"{chosen} on {len(selected)} {model} records in the Django admin"
        else:
            detail = f"{VERBS[action]} {model}{' ' + object_id if object_id else ''} in the Django admin"
        AuditLog.objects.create(
            user=user, action=action, object_type=object_type[:80],
            object_id=object_id[:80], detail=_detail(detail, ",".join(names)), ip_address=_client_ip(request),
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
        fields = fields or _summarise_body(request, form=True) or _applied_names(response)

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
        phrase = _phrase(action, segment, object_id)
        detail = _detail(phrase, fields) if phrase else _call_detail(f"{request.method} {request.path}", fields)
        AuditLog.objects.create(
            user=user, action=action, object_type=object_type[:80],
            object_id=object_id[:80], detail=detail, ip_address=ip,
        )
