"""Explicit audit events that the request middleware cannot derive on its own.

The middleware records every successful mutating API call. Authentication
events are different: a failed login has no authenticated user, and the login
endpoint is deliberately excluded from body capture so credentials never reach
the log. These helpers write those events with the same fields.
"""
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
    """Write a login / login_failed entry for a token-obtain call."""
    try:
        username = _username_from(request)
        ip = _client_ip(request)
        # The sign-in request has no workspace of its own; the entry belongs
        # to the account's workspace so its administrators can see it.
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
    """An authentication-related fact that is neither a login nor a logout:
    a factor enrolled or removed, a passkey refused, an MFA reset. The
    ``/api/auth/`` prefix is excluded from the request middleware (it carries
    credentials), so these are written explicitly, never with a value."""
    try:
        known = user is not None and getattr(user, "pk", None)
        AuditLog.objects.create(
            user=user if known else None,
            action=str(action)[:20], object_type="auth",
            object_id=str(user.pk) if known else "",
            detail=str(detail)[:255], ip_address=_client_ip(request) if request is not None else None,
            # /api/auth/ runs before a workspace is resolved, so the entry is
            # filed under the account it is about.
            workspace_id=(user.workspace_id if known else None),
        )
    except Exception:
        logger.exception("Failed to record an authentication event")


EVIDENCE_READ = "read"


def record_evidence_read(request, document, version=None):
    """Record that someone read the bytes of a stored document.

    Reading evidence is the act an auditor most needs to be able to reconstruct
    afterwards -- "who saw this file, and when" -- and until the download went
    through the API there was nothing to record it. Failures are swallowed: a
    logging problem must not stop an authorised download.
    """
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
    """Record an act on an evidence package.

    Disclosure is the thing this feature exists to make accountable, so the
    export and read events are written BEFORE the bytes leave. Failures are
    swallowed for reads and exports -- a logging problem must not deny an
    authorised auditor their evidence -- but the row is written first, so a
    successful download always has a matching entry.
    """
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
