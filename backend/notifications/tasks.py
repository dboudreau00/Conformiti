"""Scheduled review-alert scanning.

Runs daily via Celery beat (see CELERY_BEAT_SCHEDULE) or on demand via
`python manage.py send_review_reminders` for cron-based deployments.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from accounts import tenancy
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


def run_scanner_watch(dry_run=False):
    """Probe the malware scanner and email the compliance team once when it
    goes down and once when it comes back. Returns "down", "up", "recovered"
    or "off" -- what the probe found, not whether mail went out."""
    from documents import monitor
    from documents.models import ScannerStatus

    state = monitor.probe(force=True)
    if not state["enabled"]:
        return "off"
    status = ScannerStatus.load()
    now = timezone.now()
    from . import webhooks

    if state["reachable"] is False:
        if status.alerted_down_at is None or (status.down_since and status.alerted_down_at < status.down_since):
            if not dry_run:
                send_templated_email(
                    "[Alert] Malware scanner unreachable — evidence uploads are being refused",
                    "scanner_alert", {"down": True, "since": status.down_since or now},
                    [settings.COMPLIANCE_TEAM_EMAIL])
                webhooks.post_event("scanner.down", "Malware scanner unreachable",
                                    "clamd stopped answering; evidence uploads are being refused until it is back.",
                                    facts=[("Down since", (status.down_since or now).isoformat(timespec="minutes"))],
                                    path="/documents", severity="critical")
                status.alerted_down_at = now
                status.save(update_fields=["alerted_down_at"])
        return "down"
    if status.alerted_down_at and (status.alerted_up_at is None or status.alerted_up_at < status.alerted_down_at):
        if not dry_run:
            send_templated_email(
                "[Recovered] Malware scanner is answering again",
                "scanner_alert", {"down": False, "since": status.last_ok_at or now},
                [settings.COMPLIANCE_TEAM_EMAIL])
            webhooks.post_event("scanner.up", "Malware scanner is answering again",
                                "Uploads are accepted once more.", path="/documents", severity="info")
            status.alerted_up_at = now
            status.save(update_fields=["alerted_up_at"])
        return "recovered"
    return "up"


@shared_task(name="notifications.tasks.watch_scanner")
def watch_scanner():
    return run_scanner_watch()


# --------------------------------------------------------------------------- #
# Digests: a person's own tray, by email, daily or weekly
# --------------------------------------------------------------------------- #
SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def digest_items(user):
    """The tray as the person would see it: computed now, dismissed items
    left out."""
    from .models import NotificationReceipt
    from .notifications import build

    items = build(user)
    dismissed = set(NotificationReceipt.objects.filter(
        user=user, key__in=[i["key"] for i in items], dismissed_at__isnull=False,
    ).values_list("key", flat=True))
    return [i for i in items if i["key"] not in dismissed]


def run_digests(dry_run=False, today=None):
    """Email each person who asked for one the items in their tray. Daily
    means every day; weekly means Mondays. One per day at most, and none
    when the tray is empty. Returns the number sent."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    today = today or timezone.localdate()
    base = (getattr(settings, "PUBLIC_URL", "") or "").rstrip("/")
    sent = 0
    # A person's tray is computed in their own workspace; platform accounts
    # with none get no digest.
    with tenancy.unscoped():
        people = list(User.objects.filter(is_active=True, workspace__isnull=False, workspace__is_active=True)
                      .exclude(email="").exclude(digest=User.Digest.OFF))
    for user in people:
        if user.digest == User.Digest.WEEKLY and today.weekday() != 0:
            continue
        if user.digest_sent_at and timezone.localtime(user.digest_sent_at).date() >= today:
            continue
        with tenancy.scoped(user.workspace_id):
            items = digest_items(user)
        if not items:
            continue
        groups = [(sev, [i for i in items if i["severity"] == sev]) for sev in SEVERITY_ORDER]
        groups = [(sev, rows) for sev, rows in groups if rows]
        context = {
            "user": user, "items": items, "groups": groups, "count": len(items),
            "base": base, "cadence": user.get_digest_display().lower(), "today": today,
        }
        subject = f"[Conformiti] {len(items)} item{'s' if len(items) != 1 else ''} need your attention"
        try:
            if not dry_run:
                send_templated_email(subject, "digest", context, [user.email])
                user.digest_sent_at = timezone.now()
                user.save(update_fields=["digest_sent_at"])
        except Exception:
            logger.exception("Digest for %s failed; will retry next run", user.pk)
            continue
        sent += 1
    return sent


@shared_task(name="notifications.tasks.send_digests")
def send_digests():
    return run_digests()


# --------------------------------------------------------------------------- #
# The daily summary to Slack / Teams
# --------------------------------------------------------------------------- #
def post_daily_summary(today=None):
    """One chat message a day with the organisation-wide counts that need
    someone's attention. Nothing is posted when nothing is outstanding."""
    from attestations.models import EvidencePackage, PbcRequest
    from documents import monitor
    from governance.models import Risk
    from . import webhooks

    today = today or timezone.localdate()
    docs = Document.objects.filter(next_review_date__lt=today).count()
    risks = Risk.objects.filter(status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING],
                                due_date__lt=today).count()
    pbc = PbcRequest.objects.filter(status__in=PbcRequest.ACTIONABLE, due_date__lt=today).exclude(
        package__status=EvidencePackage.Status.WITHDRAWN).count()
    held = monitor.quarantined().count()
    if not (docs or risks or pbc or held):
        return []
    facts = [("Documents overdue for review", docs), ("Risks past their due date", risks),
             ("Auditor requests overdue", pbc), ("Files in quarantine", held)]
    return webhooks.post_event(
        "digest.daily", f"Conformiti daily summary — {today.isoformat()}",
        "Outstanding across the workspace this morning.",
        facts=[(k, v) for k, v in facts if v], path="/",
        severity="high" if (pbc or held) else "medium")


def run_all_scans(dry_run=False):
    """The morning pass, once per workspace. Returns per-workspace counts."""
    result = {}
    for workspace in tenancy.for_each_workspace():
        result[workspace.slug] = {
            "documents": run_review_scan(dry_run=dry_run),
            "vendors": run_vendor_scan(dry_run=dry_run),
            "pbc": run_pbc_scan(dry_run=dry_run),
        }
        if not dry_run:
            post_daily_summary()
    return result


@shared_task(name="notifications.tasks.scan_document_reviews")
def scan_document_reviews():
    return run_all_scans()
