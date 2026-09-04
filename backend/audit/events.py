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
        if response.status_code == 200:
            user = get_user_model().objects.filter(username=username).first()
            AuditLog.objects.create(
                user=user, action=LOGIN_OK, object_type="auth",
                object_id=str(user.pk) if user else "", detail=f"signed in: {username}",
                ip_address=ip,
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
