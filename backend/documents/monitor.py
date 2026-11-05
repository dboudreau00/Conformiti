"""Probes the malware scanner and re-scans stored files. A document the scanner flags is quarantined: kept on disk
for the investigation, refused by every route that serves its bytes, and recorded in the audit trail."""
import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import clamav
from .models import Document, DocumentVersion, FormTemplate, ScannerStatus

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


def _record(subject, action, detail, user=None):
    from audit.models import AuditLog

    # An archived version is audited under its document, a template under its own route.
    if isinstance(subject, DocumentVersion):
        object_type, object_id = "documents", subject.document_id
    elif isinstance(subject, FormTemplate):
        object_type, object_id = "form-templates", subject.pk
    else:
        object_type, object_id = "documents", subject.pk
    try:
        # A rescan runs with no workspace active, so the row names the tenant.
        AuditLog.objects.create(
            user=user, action=action, object_type=object_type, object_id=str(object_id),
            detail=str(detail)[:255], workspace_id=subject.workspace_id,
        )
    except Exception:  # pragma: no cover - never block the scan on bookkeeping
        logger.exception("Failed to record a scan event")


def _label(subject):
    """How the audit row and the notice name a stored file: its name, and which stored file of it is meant."""
    if isinstance(subject, DocumentVersion):
        return subject.document.name, f"archived v{subject.version}"
    if isinstance(subject, FormTemplate):
        return subject.name, "form template"
    return subject.name, f"v{subject.version}"


def _verdict(subject):
    """Opens the stored file and returns ``(status, signature, infected_exc)``; never raises for a scanner problem."""
    host, port = _endpoint()
    try:
        with subject.file.open("rb") as fh:
            clamav.scan_stream(
                fh, host, port,
                timeout=float(getattr(settings, "CLAMAV_TIMEOUT", 10)),
                connect_timeout=float(getattr(settings, "CLAMAV_CONNECT_TIMEOUT", 3)),
                max_bytes=int(getattr(settings, "CLAMAV_MAX_BYTES", 0)) or None,
            )
    except clamav.InfectedError as exc:
        return Document.Scan.INFECTED, str(exc.signature)[:200], exc
    except clamav.LimitsExceededError as exc:
        return Document.Scan.ERROR, f"not fully inspected: {exc.reason}"[:200], None
    except clamav.ScanError as exc:
        logger.error("Re-scan of %s %s failed: %s", type(subject).__name__.lower(), subject.pk, exc)
        return Document.Scan.ERROR, str(exc)[:200], None
    except (OSError, ValueError) as exc:
        return Document.Scan.ERROR, f"file unreadable: {exc}"[:200], None
    return Document.Scan.CLEAN, "", None


def scan_document(document, user=None):
    """Re-scan one stored file (a document, an archived version or a form template); returns the new ``scan_status``.
    Never raises for a scanner problem (the sweep must reach every file): a file the scanner could not inspect is
    recorded as ``error``, which is not clean. The verdict is written to the row as it stands when the scan ends, and
    only if it still holds the bytes that were scanned."""
    if not enabled():
        return document.scan_status
    if not document.file:
        return document.scan_status
    scanned_file = document.file.name
    scanned_version = getattr(document, "version", None)
    loaded_quarantine = document.quarantined_at
    status, signature, infected = _verdict(document)
    now = timezone.now()
    newly = released = False
    with transaction.atomic():
        row = type(document).objects.select_for_update().filter(pk=document.pk).first()
        # Replaced or deleted while the scanner was reading: the verdict belongs to bytes this row no longer holds.
        if row is None or row.file.name != scanned_file or getattr(row, "version", None) != scanned_version:
            return row.scan_status if row is not None else document.scan_status
        if status == Document.Scan.CLEAN and row.quarantined_at != loaded_quarantine:
            # Another sweep quarantined it after this one began: a clean answer must not undo that.
            return row.scan_status
        row.scan_status = status
        row.scan_signature = signature
        row.scanned_at = now
        if status == Document.Scan.INFECTED:
            newly = row.quarantined_at is None
            row.quarantined_at = row.quarantined_at or now
        elif status == Document.Scan.CLEAN and row.quarantined_at is not None:
            released = True
            row.quarantined_at = None
        row.save(update_fields=["scan_status", "scan_signature", "scanned_at", "quarantined_at"])
    for field in ("scan_status", "scan_signature", "scanned_at", "quarantined_at"):
        setattr(document, field, getattr(row, field))
    name, which = _label(document)
    if released:
        _record(document, "update", f"released '{name}' ({which}) from quarantine: rescan clean", user)
    if newly:
        _record(document, "delete", f"QUARANTINED '{name}' ({which}): scanner matched {infected.signature}", user)
        from accounts import tenancy
        from notifications import webhooks
        owner_doc = document if isinstance(document, Document) else getattr(document, "document", None)
        folder_path = owner_doc.folder.path if owner_doc is not None and owner_doc.folder_id else "-"
        # A rescan has no workspace active, so a bare post would go to the installation's own channel and name one
        # organisation's document to whoever reads it: post from inside the file's workspace.
        with tenancy.scoped(document.workspace_id):
            webhooks.post_event(
                "document.quarantined", f"File quarantined: {name}",
                f"The malware scanner matched {infected.signature} on a stored file ({which}). "
                "It is kept for investigation and refused on every route.",
                facts=[("Folder", folder_path)],
                path="/documents", severity="critical")
    return document.scan_status


def mark_clean(document):
    """Marks a stored file clean without scanning it: call only after an upload passed the scanner."""
    if not enabled():
        return
    document.scan_status = Document.Scan.CLEAN
    document.scan_signature = ""
    document.scanned_at = timezone.now()
    document.save(update_fields=["scan_status", "scan_signature", "scanned_at"])


def rescan(queryset=None, dry_run=False, limit=None, user=None):
    """Sweeps a queryset of documents, archived versions or form templates and returns the counts."""
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
    """Called first by every route that serves a stored file's bytes: quarantined means 403 with the signature, not 404.
    Takes a document, an archived version or a form template."""
    from rest_framework.exceptions import PermissionDenied

    if document is not None and document.quarantined_at is not None:
        quarantined_on = timezone.localtime(document.quarantined_at).date().isoformat()
        name, which = _label(document)
        raise PermissionDenied(
            f"'{name}' ({which}) is quarantined: the malware scanner matched "
            f"{document.scan_signature or 'a signature'} on {quarantined_on}. "
            "It is kept for investigation and cannot be opened or downloaded."
        )
    return document
