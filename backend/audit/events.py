"""Explicit audit events the request middleware cannot derive: a failed sign-in has no authenticated user, and
/api/auth/ is excluded from body capture so credentials never reach the log."""
import logging

from django.contrib.auth import get_user_model

from .middleware import _client_ip
from .models import AuditLog

logger = logging.getLogger(__name__)

LOGIN_OK = "login"
LOGIN_FAILED = "login_failed"
LOGOUT = "logout"


def _username_from(request):
    data = getattr(request, "data", None) or {}
    try:
        return str(data.get("username") or "")[:150]
    except AttributeError:
        return ""


def record_login_attempt(request, response):
    try:
        username = _username_from(request)
        ip = _client_ip(request)
        # No workspace is active at sign-in: file the entry under the account's, so its administrators can see it.
        user = get_user_model().objects.filter(username=username).first()
        workspace_id = user.workspace_id if user else None
        if response.status_code == 200:
            AuditLog.objects.create(
                user=user, action=LOGIN_OK, object_type="auth",
                object_id=str(user.pk) if user else "", detail=f"signed in: {username}",
                ip_address=ip, workspace_id=workspace_id,
            )
            return
        payload = getattr(response, "data", None) or {}
        detail_code = getattr(payload.get("detail"), "code", "") if isinstance(payload, dict) else ""
        if isinstance(payload, dict) and payload.get("mfa_required"):
            reason = "password ok, second factor required"
        elif detail_code == "mfa_invalid":
            reason = "invalid second factor"
        elif response.status_code == 429:
            reason = "throttled"
        else:
            reason = "invalid credentials"
        AuditLog.objects.create(
            user=None, action=LOGIN_FAILED, object_type="auth", object_id="",
            workspace_id=workspace_id,
            detail=f"sign-in failed for {username or '<blank>'}: {reason}"[:255],
            ip_address=ip,
        )
    except Exception:  # never let audit bookkeeping break authentication
        logger.exception("Failed to record login attempt")


def record_admin_sign_in(request, username, reason=None):
    """Admin sign-in; ``reason`` is None on success, else why it was refused. Never records a password or code."""
    try:
        username = str(username or "")[:150]
        user = get_user_model().objects.filter(username=username).first() if username else None
        ok = reason is None
        AuditLog.objects.create(
            user=user if ok else None, action=LOGIN_OK if ok else LOGIN_FAILED,
            object_type="auth", object_id=str(user.pk) if (ok and user) else "",
            detail=(f"signed in to the Django admin: {username}" if ok
                    else f"Django admin sign-in failed for {username or '<blank>'}: {reason}")[:255],
            ip_address=_client_ip(request) if request is not None else None,
            workspace_id=user.workspace_id if user else None,
        )
    except Exception:  # never let audit bookkeeping break authentication
        logger.exception("Failed to record an admin sign-in")


def record_logout(request):
    try:
        AuditLog.objects.create(
            user=request.user, action=LOGOUT, object_type="auth",
            object_id=str(request.user.pk), detail="signed out",
            ip_address=_client_ip(request),
        )
    except Exception:
        logger.exception("Failed to record logout")


def record_auth_event(request, user, action, detail):
    """An authentication fact that is neither login nor logout (factor added or removed, passkey refused, MFA reset).
    /api/auth/ is skipped by the middleware, so callers write these explicitly and never pass a value in ``detail``."""
    try:
        known = user is not None and getattr(user, "pk", None)
        AuditLog.objects.create(
            user=user if known else None,
            action=str(action)[:20], object_type="auth",
            object_id=str(user.pk) if known else "",
            detail=str(detail)[:255], ip_address=_client_ip(request) if request is not None else None,
            # /api/auth/ runs before a workspace is resolved: file the entry under the account it is about.
            workspace_id=(user.workspace_id if known else None),
        )
    except Exception:
        logger.exception("Failed to record an authentication event")


EVIDENCE_READ = "read"


def record_evidence_read(request, document, version=None):
    """Record a read of a stored document's bytes. A failed write is logged and never blocks the download."""
    try:
        label = f"v{version}" if version is not None else f"v{document.version}"
        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=EVIDENCE_READ, object_type="documents",
            object_id=str(document.pk),
            detail=f"downloaded {label}: {document.name}"[:255],
            ip_address=_client_ip(request),
        )
    except Exception:
        logger.exception("Failed to record an evidence download")


PACKAGE_ACTIONS = {"create", "update", "delete", "seal", "withdraw", "export", "read"}


def record_package_event(request, package, action, detail):
    """Record an act on an evidence package. Callers write export and read events before the bytes leave;
    a failed write is logged, not raised, so an authorised auditor is never denied their evidence."""
    try:
        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action=action if action in PACKAGE_ACTIONS else "update",
            object_type="evidence-packages",
            object_id=str(package.pk),
            detail=str(detail)[:255],
            ip_address=_client_ip(request),
        )
    except Exception:
        logger.exception("Failed to record an evidence-package event")
