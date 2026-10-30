"""Malware scanning of uploads. Enabled means fail-closed: there is deliberately no fail-open switch."""
import logging

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

from . import clamav

logger = logging.getLogger(__name__)

eicar_bytes = clamav.eicar_bytes


class ScannerUnavailable(APIException):
    status_code = 503
    default_detail = (
        "Evidence cannot be accepted right now: the malware scanner is unavailable. "
        "The file has not been stored. Try again shortly."
    )
    default_code = "scanner_unavailable"


class InfectedUpload(ValidationError):
    def __init__(self, signature, filename=""):
        self.signature = signature
        self.filename = filename
        super().__init__({"file": [
            f"This file was refused: the malware scanner matched {signature}. "
            "It has not been stored."
        ]})


def enabled():
    return bool(getattr(settings, "CLAMAV_ENABLED", False))


def scan_or_raise(uploaded, request=None):
    """Scan an upload before it is stored and return it unchanged. Call it after the permission check, never from
    validation: an unauthorised caller must not reach the scanner (signature oracle, saturation)."""
    if not enabled() or uploaded is None:
        return uploaded

    host = getattr(settings, "CLAMAV_HOST", "clamav")
    port = int(getattr(settings, "CLAMAV_PORT", 3310))
    timeout = float(getattr(settings, "CLAMAV_TIMEOUT", 10))
    connect_timeout = float(getattr(settings, "CLAMAV_CONNECT_TIMEOUT", 3))
    max_bytes = int(getattr(settings, "CLAMAV_MAX_BYTES", 0)) or None

    try:
        clamav.scan_stream(uploaded, host, port, timeout=timeout,
                           connect_timeout=connect_timeout, max_bytes=max_bytes)
    except clamav.InfectedError as exc:
        _record(request, uploaded, exc.signature)
        raise InfectedUpload(exc.signature, getattr(uploaded, "name", ""))
    except clamav.LimitsExceededError as exc:
        # Refused but not recorded as malware: the scanner declined to inspect the whole file.
        raise ValidationError({"file": [
            "This file could not be fully inspected by the malware scanner "
            f"({exc.reason}), so it has not been stored. Split it or upload a "
            "smaller export."
        ]})
    except clamav.ScanError as exc:
        logger.error("Evidence scan failed: %s", exc)
        raise ScannerUnavailable()
    return uploaded


def _record(request, uploaded, signature):
    from audit.middleware import _client_ip
    from audit.models import AuditLog

    try:
        user = getattr(request, "user", None)
        AuditLog.objects.create(
            user=user if (user is not None and user.is_authenticated) else None,
            action="delete", object_type="documents", object_id="0",
            detail=f"refused infected upload '{getattr(uploaded, 'name', '?')}': {signature}"[:255],
            ip_address=_client_ip(request) if request is not None else None,
        )
    except Exception:  # pragma: no cover - never block the refusal
        logger.exception("Failed to record a malware detection")
