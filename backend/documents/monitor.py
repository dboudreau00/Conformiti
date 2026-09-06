"""
Watching the malware scanner, and re-scanning what is already stored.

0.3.0 put the boundary in place: an upload is scanned when scanning is on,
and refused when the scanner cannot be reached. This module watches that
boundary and looks behind it:

* ``probe()`` -- is clamd answering? Cached briefly so the health endpoint
  and the tray can ask cheaply; the result is also written to a one-row
  table so every worker agrees on when the outage began and whether it has
  been announced.
* ``scan_document()`` -- run a stored file through clamd again. Signatures
  arrive after files do; a document that was clean on upload can be malware
  by next month's definitions. An infected file is **quarantined**: it stays
  on disk for the investigation, but every route that serves its bytes
  refuses it, and the fact is in the audit trail.
* ``rescan()`` -- the sweep ``manage.py scan_evidence`` runs.
"""
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import clamav
from .models import Document, ScannerStatus

logger = logging.getLogger(__name__)

PROBE_TTL = 60
_CACHE_KEY = "documents.monitor.probe"


def enabled():
    return bool(getattr(settings, "CLAMAV_ENABLED", False))


def _endpoint():
    return (getattr(settings, "CLAMAV_HOST", "clamav"), int(getattr(settings, "CLAMAV_PORT", 3310)))


def probe(force=False):
    """The scanner's state as a dict: ``{"enabled", "reachable", "checked_at",
    "latency_ms", "down_since"}``. Off means reachable is None."""
    if not enabled():
        return {"enabled": False, "reachable": None, "checked_at": None, "latency_ms": None,
                "down_since": None}
    if not force:
        cached = cache.get(_CACHE_KEY)
        if cached:
            return cached
    host, port = _endpoint()
    timeout = float(getattr(settings, "CLAMAV_CONNECT_TIMEOUT", 3))
    started = time.monotonic()
    reachable = clamav.ping(host, port, timeout=timeout)
    latency = int((time.monotonic() - started) * 1000)
    now = timezone.now()
    status = ScannerStatus.load()
    if reachable:
        status.reachable = True
        status.down_since = None
        status.last_ok_at = now
    else:
        status.reachable = False
        status.down_since = status.down_since or now
    status.checked_at = now
    status.save()
    result = {"enabled": True, "reachable": reachable, "checked_at": now,
              "latency_ms": latency if reachable else None, "down_since": status.down_since}
    cache.set(_CACHE_KEY, result, PROBE_TTL)
    return result


def _record(document, action, detail, user=None):
    from audit.models import AuditLog

    try:
        AuditLog.objects.create(
            user=user, action=action, object_type="documents", object_id=str(document.pk),
            detail=str(detail)[:255],
        )
    except Exception:  # pragma: no cover - never block the scan on bookkeeping
        logger.exception("Failed to record a scan event")


def scan_document(document, user=None):
    """Re-scan one stored document. Returns the new ``scan_status``.

    Never raises for a scanner problem: the sweep must reach every file, and
    a file the scanner could not inspect is recorded as ``error``, which is
    a different fact from clean.
    """
    if not enabled():
        return document.scan_status
    if not document.file:
        return document.scan_status
    host, port = _endpoint()
    now = timezone.now()
    try:
        with document.file.open("rb") as fh:
            clamav.scan_stream(
                fh, host, port,
                timeout=float(getattr(settings, "CLAMAV_TIMEOUT", 10)),
                connect_timeout=float(getattr(settings, "CLAMAV_CONNECT_TIMEOUT", 3)),
                max_bytes=int(getattr(settings, "CLAMAV_MAX_BYTES", 0)) or None,
            )
    except clamav.InfectedError as exc:
        document.scan_status = Document.Scan.INFECTED
        document.scan_signature = str(exc.signature)[:200]
        document.scanned_at = now
        newly = document.quarantined_at is None
        document.quarantined_at = document.quarantined_at or now
        document.save(update_fields=["scan_status", "scan_signature", "scanned_at", "quarantined_at"])
        if newly:
            _record(document, "delete",
                    f"QUARANTINED '{document.name}' v{document.version}: scanner matched {exc.signature}", user)
        return document.scan_status
    except clamav.LimitsExceededError as exc:
        document.scan_status = Document.Scan.ERROR
        document.scan_signature = f"not fully inspected: {exc.reason}"[:200]
    except clamav.ScanError as exc:
        logger.error("Re-scan of document %s failed: %s", document.pk, exc)
        document.scan_status = Document.Scan.ERROR
        document.scan_signature = str(exc)[:200]
    except (OSError, ValueError) as exc:
        document.scan_status = Document.Scan.ERROR
        document.scan_signature = f"file unreadable: {exc}"[:200]
    else:
        document.scan_status = Document.Scan.CLEAN
        document.scan_signature = ""
        if document.quarantined_at is not None:
            # Definitions change both ways; a false positive withdrawn
            # upstream releases the file, and that is recorded too.
            _record(document, "update", f"released '{document.name}' from quarantine: rescan clean", user)
            document.quarantined_at = None
    document.scanned_at = now
    document.save(update_fields=["scan_status", "scan_signature", "scanned_at", "quarantined_at"])
    return document.scan_status


def mark_clean(document):
    """Called after an upload passed the scanner, so the sweep does not have
    to look at it again this month."""
    if not enabled():
        return
    document.scan_status = Document.Scan.CLEAN
    document.scan_signature = ""
    document.scanned_at = timezone.now()
    document.save(update_fields=["scan_status", "scan_signature", "scanned_at"])


def rescan(queryset=None, dry_run=False, limit=None, user=None):
    """Sweep stored documents. Returns counters."""
    qs = queryset if queryset is not None else Document.objects.all()
    qs = qs.order_by("scanned_at", "pk")
    if limit:
        qs = qs[:limit]
    counts = {"scanned": 0, "clean": 0, "infected": 0, "error": 0, "skipped": 0}
    for document in qs.iterator():
        if not document.file:
            counts["skipped"] += 1
            continue
        if dry_run:
            counts["scanned"] += 1
            continue
        result = scan_document(document, user=user)
        counts["scanned"] += 1
        counts[result if result in counts else "error"] += 1
    return counts


def quarantined():
    return Document.objects.filter(quarantined_at__isnull=False)


def refuse_if_quarantined(document):
    """Every route that serves a document's bytes calls this first. A
    quarantined file is a 403 with the signature, never a silent 404: the
    person asking is entitled to know why they cannot have it."""
    from rest_framework.exceptions import PermissionDenied

    if document is not None and document.quarantined_at is not None:
        raise PermissionDenied(
            f"'{document.name}' is quarantined: the malware scanner matched "
            f"{document.scan_signature or 'a signature'} on {document.quarantined_at.date().isoformat()}. "
            "It is kept for investigation and cannot be opened or downloaded."
        )
    return document
