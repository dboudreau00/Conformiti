"""Scheduled review-alert scanning.

Runs daily via Celery beat (see CELERY_BEAT_SCHEDULE) or on demand via
`python manage.py send_review_reminders` for cron-based deployments.
"""
import logging
from datetime import date

from celery import shared_task
from django.conf import settings

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
    today = date.today()
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


@shared_task(name="notifications.tasks.scan_document_reviews")
def scan_document_reviews():
    return run_review_scan()
