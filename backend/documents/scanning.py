"""
Where an upload gets scanned, and what happens when it cannot be.

**Scanning happens after authorization, never during validation.** DRF runs
``serializer.is_valid()`` before ``perform_create``, so a hook in
``validate_upload`` would scan a file for a caller who has not yet been shown
to have edit rights on the folder — handing anyone with an account an oracle
("which of my payloads does their signature set catch?") and a way to saturate
the scanner with 32 MB uploads that fail closed into org-wide 503s.

**Enabled means fail-closed.** There is deliberately no fail-open switch: an
"is evidence scanned?" answer that depends on whether the scanner happened to
be reachable is not an answer an auditor can use. If scanning is on and the
scanner is unreachable, the upload is refused.
"""
import logging

from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

from . import clamav

logger = logging.getLogger(__name__)

# The EICAR test string, split so no contiguous copy of it exists in the
# repository for an on-access scanner to quarantine.
_EICAR_HEAD = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-"
_EICAR_TAIL = rb"ANTIVIRUS-TEST-FILE!$H+H*"


def eicar_bytes():
    """The 68-byte EICAR test file, assembled at call time."""
    return _EICAR_HEAD + _EICAR_TAIL


class ScannerUnavailable(APIException):
    """503, not 400: nothing is wrong with the caller's request."""
    status_code = 503
    default_detail = (
        "Evidence cannot be accepted right now: the malware scanner is unavailable. "
        "The file has not been stored. Try again shortly."
    )
    default_code = "scanner_unavailable"


class InfectedUpload(ValidationError):
    """400 with the signature name, and an audit row written beside it."""

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
    """Scan an uploaded file before it is stored. Returns it unchanged.

    Call from ``perform_create`` / ``perform_update``, after the folder
    permission check.
    """
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
        # Refused, but not recorded as malware: the scanner declined to inspect
        # the whole file, which is a different fact.
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
    """Write the detection to the audit trail.

    Deliberately its own row rather than a log line: "we refused a malicious
    upload, from whom, when" is exactly the sort of thing this product exists
    to be able to answer later.
    """
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
