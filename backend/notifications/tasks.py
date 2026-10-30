import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from accounts import tenancy
from documents.models import Document
from documents.serializers import person_name
from .email_service import send_templated_email
from .wording import count_of

logger = logging.getLogger(__name__)

OVERDUE = -1  # stored in reminders_sent beside the lead-day windows


def compliance_inbox():
    """The workspace's own notification address, else the setting. Subject lines carry document, vendor and auditor
    request names, so one installation-wide inbox would expose every tenant to whoever runs the installation."""
    workspace = tenancy.current()
    own = (getattr(workspace, "notification_email", "") or "").strip() if workspace else ""
    return own or settings.COMPLIANCE_TEAM_EMAIL


def _notify(document, days, overdue, window=None):
    recipients = []
    if document.owner and document.owner.email:
        recipients.append(document.owner.email)
    recipients.append(compliance_inbox())

    if overdue:
        subject = f"[Overdue] Review overdue: {document.name}"
    else:
        subject = f"[Reminder] Review due in {count_of(days, 'day')}: {document.name}"

    context = {
        "document": document,
        "days": days,
        "overdue": overdue,
        "window": window,
        "owner_name": person_name(document.owner) or "team",
        "folder_path": document.folder.path if document.folder_id else "",
    }
    return send_templated_email(subject, "review_reminder", context, recipients)


def run_review_scan(dry_run=False):
    """One email per document per run, for the most urgent lead-time window it newly entered; overdue documents are
    marked expired. With ``dry_run`` nothing is emailed or saved. Returns the number notified (or that would be)."""
    today = timezone.localdate()
    leads = settings.REVIEW_ALERT_LEAD_DAYS
    notified = 0

    qs = Document.objects.filter(next_review_date__isnull=False).select_related("owner", "folder")
    for doc in qs:
        days = (doc.next_review_date - today).days
        before = list(doc.reminders_sent or [])
        sent = list(before)
        window = None
        overdue = False

        if days < 0:
            if OVERDUE not in sent:
                sent.append(OVERDUE)
                overdue = True
        else:
            applicable = sorted(l for l in leads if days <= l)
            if applicable and any(l not in sent for l in applicable):
                sent = sorted(set(sent) | set(applicable))
                window = min(applicable)
        if sent == before:
            continue
        notified += 1
        if dry_run:
            continue

        # Claim the window before sending, with a conditional UPDATE that only matches while the row still holds what
        # this worker read: of two concurrent scans only one wins, so the document is not emailed twice.
        fields = {"reminders_sent": sent}
        if overdue:
            fields["status"] = Document.Status.EXPIRED
        claimed = Document.objects.filter(pk=doc.pk, reminders_sent=before).update(**fields)
        if not claimed:
            continue

        # A failing send must not abort the scan; the claim is handed back so the next run retries.
        try:
            _notify(doc, days, overdue=overdue, window=window)
        except Exception:
            logger.exception(
                "Review reminder failed for document %s; will retry next run", doc.pk
            )
            Document.objects.filter(pk=doc.pk, reminders_sent=sent).update(
                reminders_sent=before, status=doc.status)
            notified -= 1

    return notified


def _notify_bridge(vendor, report):
    recipients = []
    if vendor.owner and vendor.owner.email:
        recipients.append(vendor.owner.email)
    recipients.append(compliance_inbox())
    subject = f"[Action] Bridge letter needed from {vendor.name}"
    context = {
        "vendor": vendor, "report": report,
        "owner_name": person_name(vendor.owner) or "team",
        "lapsed_on": report.expires_at,
        "days": (timezone.localdate() - report.expires_at).days,
    }
    return send_templated_email(subject, "bridge_letter", context, recipients)


def run_vendor_scan(dry_run=False):
    """Email the owner and the compliance team once per lapsed SOC report with no newer report or bridge letter; the
    report remembers it was chased. Returns the number chased."""
    from vendors.assurance import bridge_letter_gaps

    chased = 0
    for vendor, report in bridge_letter_gaps():
        if report.bridge_reminded_at:
            continue
        if not dry_run:
            # Claim, then send: two concurrent runs would both see "not yet chased" and both email.
            now = timezone.now()
            model = type(report)
            claimed = model.objects.filter(pk=report.pk, bridge_reminded_at__isnull=True).update(
                bridge_reminded_at=now)
            if not claimed:
                continue
            try:
                _notify_bridge(vendor, report)
            except Exception:
                logger.exception("Bridge-letter reminder failed for vendor %s; will retry next run", vendor.pk)
                model.objects.filter(pk=report.pk, bridge_reminded_at=now).update(bridge_reminded_at=None)
                continue
        chased += 1
    return chased


def _notify_pbc(req, days, overdue, window=None):
    recipients = []
    if req.assignee and req.assignee.email:
        recipients.append(req.assignee.email)
    recipients.append(compliance_inbox())
    if overdue:
        subject = f"[Overdue] Auditor request {req.reference} overdue: {req.title}"
    else:
        subject = f"[Reminder] Auditor request {req.reference} due in {count_of(days, 'day')}: {req.title}"
    context = {
        "request": req, "package": req.package, "days": days, "overdue": overdue, "window": window,
        "assignee_name": person_name(req.assignee) or "team",
    }
    return send_templated_email(subject, "pbc_reminder", context, recipients)


def run_pbc_scan(dry_run=False):
    """Email each auditor request once per lead-time window (REVIEW_ALERT_LEAD_DAYS) and once when overdue; a line the
    auditor is sitting on is skipped. Returns the count."""
    from attestations.models import EvidencePackage, PbcRequest

    today = timezone.localdate()
    leads = settings.REVIEW_ALERT_LEAD_DAYS
    notified = 0
    qs = PbcRequest.objects.filter(
        status__in=PbcRequest.ACTIONABLE, due_date__isnull=False,
    ).exclude(package__status=EvidencePackage.Status.WITHDRAWN).select_related("assignee", "package")
    for req in qs:
        days = (req.due_date - today).days
        before = list(req.reminders_sent or [])
        sent = list(before)
        window = None
        overdue = False
        if days < 0:
            if OVERDUE not in sent:
                sent.append(OVERDUE)
                overdue = True
        else:
            applicable = sorted(l for l in leads if days <= l)
            if applicable and any(l not in sent for l in applicable):
                sent = sorted(set(sent) | set(applicable))
                window = min(applicable)
        if sent == before:
            continue
        notified += 1
        if dry_run:
            continue
        # Claim before sending, as in run_review_scan: the conditional UPDATE stops two concurrent runs sending twice.
        claimed = PbcRequest.objects.filter(pk=req.pk, reminders_sent=before).update(
            reminders_sent=sent)
        if not claimed:
            continue
        try:
            _notify_pbc(req, days, overdue=overdue, window=window)
        except Exception:
            logger.exception("PBC reminder failed for request %s; will retry next run", req.pk)
            PbcRequest.objects.filter(pk=req.pk, reminders_sent=sent).update(reminders_sent=before)
            notified -= 1
    return notified


def run_scanner_watch(dry_run=False):
    """Email the compliance team once when the malware scanner goes down and once when it recovers. Returns "down",
    "up", "recovered" or "off": what the probe found, not whether mail went out."""
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
                    "[Alert] Malware scanner unreachable: evidence uploads are being refused",
                    "scanner_alert", {"down": True, "since": status.down_since or now},
                    [compliance_inbox()])
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
                [compliance_inbox()])
            webhooks.post_event("scanner.up", "Malware scanner is answering again",
                                "Uploads are accepted once more.", path="/documents", severity="info")
            status.alerted_up_at = now
            status.save(update_fields=["alerted_up_at"])
        return "recovered"
    return "up"


@shared_task(name="notifications.tasks.watch_scanner")
def watch_scanner():
    return run_scanner_watch()


SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def digest_items(user):
    """The person's tray as the bell shows it: computed now, dismissed items left out."""
    from .models import NotificationReceipt
    from .notifications import build

    items = build(user)
    dismissed = set(NotificationReceipt.objects.filter(
        user=user, key__in=[i["key"] for i in items], dismissed_at__isnull=False,
    ).values_list("key", flat=True))
    return [i for i in items if i["key"] not in dismissed]


def run_digests(dry_run=False, today=None):
    """Email each person who asked for a digest the items in their tray: daily people every day, weekly people on
    Mondays, at most one a day and none for an empty tray. Returns the number sent."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    today = today or timezone.localdate()
    base = (getattr(settings, "PUBLIC_URL", "") or "").rstrip("/")
    sent = 0
    # A tray is computed in the person's own workspace; platform accounts with none get no digest.
    with tenancy.unscoped():
        people = list(User.objects.filter(is_active=True, workspace__isnull=False, workspace__is_active=True)
                      .exclude(email="").exclude(digest=User.Digest.OFF))
    for user in people:
        if user.digest == User.Digest.WEEKLY and today.weekday() != 0:
            continue
        if user.digest_sent_at and timezone.localtime(user.digest_sent_at).date() >= today:
            continue
        try:
            with tenancy.scoped(user.workspace_id):
                items = digest_items(user)
        except Exception:
            # One person's tray failing must not stop everyone else's digest.
            logger.exception("Digest for %s could not be built; will retry next run", user.pk)
            continue
        if not items:
            continue
        groups = [(sev, [i for i in items if i["severity"] == sev]) for sev in SEVERITY_ORDER]
        groups = [(sev, rows) for sev, rows in groups if rows]
        context = {
            "user": user, "items": items, "groups": groups, "count": len(items),
            "base": base, "cadence": user.get_digest_display().lower(), "today": today,
        }
        needs = "needs" if len(items) == 1 else "need"
        subject = f"[Conformiti] {count_of(len(items), 'item')} {needs} your attention"
        if not dry_run:
            # Claim today's digest before sending: a concurrent run finds the stamp moved and sends nothing.
            now = timezone.now()
            with tenancy.unscoped():
                claimed = User.objects.filter(pk=user.pk, digest_sent_at=user.digest_sent_at).update(
                    digest_sent_at=now)
            if not claimed:
                continue
            try:
                send_templated_email(subject, "digest", context, [user.email])
            except Exception:
                logger.exception("Digest for %s failed; will retry next run", user.pk)
                with tenancy.unscoped():
                    User.objects.filter(pk=user.pk, digest_sent_at=now).update(
                        digest_sent_at=user.digest_sent_at)
                continue
        sent += 1
    return sent


@shared_task(name="notifications.tasks.send_digests")
def send_digests():
    return run_digests()


def post_daily_summary(today=None):
    """Post the workspace's outstanding counts (overdue documents, risks and auditor requests; quarantined files) to the
    chat channels; returns [] without posting when nothing is outstanding."""
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
        "digest.daily", f"Conformiti daily summary: {today.isoformat()}",
        "Outstanding across the workspace this morning.",
        facts=[(k, v) for k, v in facts if v], path="/",
        severity="high" if (pbc or held) else "medium")


def run_all_scans(dry_run=False):
    """The morning pass for each workspace. Returns ``{slug: counts}``, with None for a workspace whose scan failed."""
    result = {}
    for workspace in tenancy.for_each_workspace():
        # One organisation's failure must not stop the rest of the installation's morning pass.
        try:
            result[workspace.slug] = {
                "documents": run_review_scan(dry_run=dry_run),
                "vendors": run_vendor_scan(dry_run=dry_run),
                "pbc": run_pbc_scan(dry_run=dry_run),
            }
            if not dry_run:
                post_daily_summary()
        except Exception:
            logger.exception("Morning scan failed for workspace %s", workspace.slug)
            result[workspace.slug] = None
    return result


@shared_task(name="notifications.tasks.scan_document_reviews")
def scan_document_reviews():
    return run_all_scans()
