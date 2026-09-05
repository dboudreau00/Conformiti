"""Scheduled review-alert scanning.

Runs daily via Celery beat (see CELERY_BEAT_SCHEDULE) or on demand via
`python manage.py send_review_reminders` for cron-based deployments.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from documents.models import Document
from .email_service import send_templated_email

logger = logging.getLogger(__name__)

OVERDUE = -1  # sentinel stored in Document.reminders_sent


def _notify(document, days, overdue, window=None):
    recipients = []
    if document.owner and document.owner.email:
        recipients.append(document.owner.email)
    recipients.append(settings.COMPLIANCE_TEAM_EMAIL)

    if overdue:
        subject = f"[Overdue] Review overdue: {document.name}"
    else:
        subject = f"[Reminder] Review due in {days} day(s): {document.name}"

    context = {
        "document": document,
        "days": days,
        "overdue": overdue,
        "window": window,
        "owner_name": document.owner.get_full_name() if document.owner else "team",
        "folder_path": document.folder.path if document.folder_id else "",
    }
    return send_templated_email(subject, "review_reminder", context, recipients)


def run_review_scan(dry_run=False):
    """
    Send at most one reminder per document per run: the most urgent lead-time
    window it has newly entered. Overdue documents get one overdue notice and
    are marked expired. Never sends a duplicate for the same window.

    With ``dry_run=True`` nothing is emailed or saved; the return value is the
    number of documents that *would* be notified. Returns the notified count.
    """
    today = timezone.localdate()
    leads = settings.REVIEW_ALERT_LEAD_DAYS
    notified = 0

    qs = Document.objects.filter(next_review_date__isnull=False).select_related("owner", "folder")
    for doc in qs:
        days = (doc.next_review_date - today).days
        sent = list(doc.reminders_sent or [])
        changed = False

        # Isolate each document: a failing send (bad address, provider/network
        # error) must not abort the whole scan and starve every document after
        # it. On failure we skip persisting this doc's state so it retries next
        # run, and move on.
        try:
            if days < 0:
                if OVERDUE not in sent:
                    if not dry_run:
                        _notify(doc, days, overdue=True)
                    sent.append(OVERDUE)
                    doc.status = Document.Status.EXPIRED
                    changed = True
            else:
                applicable = sorted(l for l in leads if days <= l)
                if applicable and any(l not in sent for l in applicable):
                    if not dry_run:
                        _notify(doc, days, overdue=False, window=min(applicable))
                    sent = sorted(set(sent) | set(applicable))
                    changed = True
        except Exception:
            logger.exception(
                "Review reminder failed for document %s; will retry next run", doc.pk
            )
            continue

        if changed:
            notified += 1
            if not dry_run:
                doc.reminders_sent = sent
                doc.save(update_fields=["reminders_sent", "status"])

    return notified


def _notify_bridge(vendor, report):
    recipients = []
    if vendor.owner and vendor.owner.email:
        recipients.append(vendor.owner.email)
    recipients.append(settings.COMPLIANCE_TEAM_EMAIL)
    subject = f"[Action] Bridge letter needed from {vendor.name}"
    context = {
        "vendor": vendor, "report": report,
        "owner_name": vendor.owner.get_full_name() if vendor.owner else "team",
        "lapsed_on": report.expires_at,
        "days": (timezone.localdate() - report.expires_at).days,
    }
    return send_templated_email(subject, "bridge_letter", context, recipients)


def run_vendor_scan(dry_run=False):
    """Email the owner (and the compliance team) once for every SOC report
    that has lapsed with no newer report and no bridge letter on file.

    One email per lapse: the report remembers it was chased, and the in-app
    feed keeps nagging until a letter is filed. Returns the number chased.
    """
    from vendors.assurance import bridge_letter_gaps

    chased = 0
    for vendor, report in bridge_letter_gaps():
        if report.bridge_reminded_at:
            continue
        try:
            if not dry_run:
                _notify_bridge(vendor, report)
                report.bridge_reminded_at = timezone.now()
                report.save(update_fields=["bridge_reminded_at"])
        except Exception:
            logger.exception("Bridge-letter reminder failed for vendor %s; will retry next run", vendor.pk)
            continue
        chased += 1
    return chased


def _notify_pbc(req, days, overdue, window=None):
    recipients = []
    if req.assignee and req.assignee.email:
        recipients.append(req.assignee.email)
    recipients.append(settings.COMPLIANCE_TEAM_EMAIL)
    if overdue:
        subject = f"[Overdue] Auditor request {req.reference} overdue: {req.title}"
    else:
        subject = f"[Reminder] Auditor request {req.reference} due in {days} day(s): {req.title}"
    context = {
        "request": req, "package": req.package, "days": days, "overdue": overdue, "window": window,
        "assignee_name": req.assignee.get_full_name() if req.assignee else "team",
    }
    return send_templated_email(subject, "pbc_reminder", context, recipients)


def run_pbc_scan(dry_run=False):
    """Chase the auditor's request list: at most one email per request per
    lead-time window (REVIEW_ALERT_LEAD_DAYS), one overdue notice, and
    nothing for a line the auditor is sitting on. Returns the count."""
    from attestations.models import EvidencePackage, PbcRequest

    today = timezone.localdate()
    leads = settings.REVIEW_ALERT_LEAD_DAYS
    notified = 0
    qs = PbcRequest.objects.filter(
        status__in=PbcRequest.ACTIONABLE, due_date__isnull=False,
    ).exclude(package__status=EvidencePackage.Status.WITHDRAWN).select_related("assignee", "package")
    for req in qs:
        days = (req.due_date - today).days
        sent = list(req.reminders_sent or [])
        changed = False
        try:
            if days < 0:
                if OVERDUE not in sent:
                    if not dry_run:
                        _notify_pbc(req, days, overdue=True)
                    sent.append(OVERDUE)
                    changed = True
            else:
                applicable = sorted(l for l in leads if days <= l)
                if applicable and any(l not in sent for l in applicable):
                    if not dry_run:
                        _notify_pbc(req, days, overdue=False, window=min(applicable))
                    sent = sorted(set(sent) | set(applicable))
                    changed = True
        except Exception:
            logger.exception("PBC reminder failed for request %s; will retry next run", req.pk)
            continue
        if changed:
            notified += 1
            if not dry_run:
                req.reminders_sent = sent
                req.save(update_fields=["reminders_sent"])
    return notified


@shared_task(name="notifications.tasks.scan_document_reviews")
def scan_document_reviews():
    notified = run_review_scan()
    run_vendor_scan()
    run_pbc_scan()
    return notified
