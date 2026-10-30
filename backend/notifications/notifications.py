"""Per-user notifications computed on request, not stored. Each item's ``key`` must stay stable: read and dismissed
state (NotificationReceipt) is stored against it."""
from .wording import count_of

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
MAX_ITEMS = 40


def _n(key, category, severity, title, detail, to, as_of=None):
    return {
        "key": key,
        "category": category,
        "severity": severity,
        "title": title,
        "detail": detail,
        "to": to,
        "as_of": as_of.isoformat() if as_of else None,
    }


# Each source imports its models inside its function, so this module loads without Django configured and takes no part
# in app-load ordering.
def _document_items(user, today):
    from documents.models import Document

    items = []
    my_docs = (
        Document.objects.filter(owner=user)
        .exclude(next_review_date__isnull=True)
        .select_related("folder")
    )
    for d in my_docs:
        days = (d.next_review_date - today).days
        if days < 0:
            items.append(_n(
                f"doc-overdue:{d.id}", "doc_review", "high",
                f"Review overdue: {d.name}",
                f"Was due {d.next_review_date.isoformat()} ({-days}d ago)",
                "/documents", d.next_review_date,
            ))
        elif days <= 14:
            items.append(_n(
                f"doc-due:{d.id}", "doc_review", "medium",
                f"Review due soon: {d.name}",
                f"Due {d.next_review_date.isoformat()} ({days}d)",
                "/documents", d.next_review_date,
            ))
    return items


def _vendor_items(user, today):
    from compliance.models import Control
    from django.utils import timezone
    from vendors.assurance import bridge_letter_gaps
    from vendors.models import QuestionnaireInvite, SharedResponsibility, Vendor, VendorAssessment

    items = []
    my_vendors = Vendor.objects.filter(
        owner=user, status__in=("active", "offboarding")).prefetch_related("assessments")
    for v in my_vendors:
        if v.next_review_date and v.next_review_date < today:
            items.append(_n(
                f"vendor-review:{v.id}", "vendor", "high",
                f"Vendor review overdue: {v.name}",
                f"Was due {v.next_review_date.isoformat()}", "/vendors", v.next_review_date,
            ))
        posture = v.assurance()["posture"]
        if posture in ("expired", "none") and v.tier in ("critical", "high"):
            items.append(_n(
                f"vendor-assurance:{v.id}", "vendor", "high",
                f"No current assurance over {v.name}",
                f"{v.get_tier_display()} vendor with {'expired' if posture == 'expired' else 'no'} "
                "assessment on file", "/vendors",
            ))
    can_prompt = user.is_superuser or user.can_manage_frameworks
    prompt_vendors = Vendor.objects.filter(status__in=("prospective", "active"))
    if not can_prompt:
        prompt_vendors = prompt_vendors.filter(owner=user)
    total_controls = Control.objects.exclude(status="not_applicable").count()
    for v in prompt_vendors.select_related("owner"):
        stated = SharedResponsibility.objects.filter(vendor=v).count()
        if stated == 0:
            age = (today - v.created_at.date()).days
            severity = "high" if v.tier in ("critical", "high") else "medium"
            items.append(_n(
                f"vendor-onboard:{v.id}", "vendor", severity,
                f"New vendor: state responsibilities for {v.name}",
                f"No shared responsibility matrix yet ({age}d since onboarding). "
                "Record which controls they cover, or import their matrix.",
                f"/vendors?vendor={v.id}&tab=matrix", v.created_at.date(),
            ))
        elif total_controls and stated < total_controls * 0.5 and v.tier in ("critical", "high"):
            items.append(_n(
                f"vendor-matrix-partial:{v.id}", "vendor", "low",
                f"Responsibility matrix incomplete: {v.name}",
                f"{stated} of {total_controls} controls stated.",
                f"/vendors?vendor={v.id}&tab=matrix",
            ))

    soon = today + timezone.timedelta(days=60)
    for a in VendorAssessment.objects.filter(
        vendor__owner=user, expires_at__gte=today, expires_at__lte=soon
    ).select_related("vendor"):
        days = (a.expires_at - today).days
        items.append(_n(
            f"vendor-expiry:{a.id}", "vendor", "medium",
            f"{a.get_kind_display()} expires for {a.vendor.name}",
            f"Expires {a.expires_at.isoformat()} ({days}d)",
            f"/vendors?vendor={a.vendor_id}&tab=assessments", a.expires_at,
        ))
    for vendor, report in bridge_letter_gaps(user):
        items.append(_n(
            f"vendor-bridge:{vendor.id}", "vendor",
            "high" if vendor.tier in ("critical", "high") else "medium",
            f"Bridge letter needed from {vendor.name}",
            f"{report.get_kind_display()} lapsed on {report.expires_at.isoformat()} and nothing "
            "newer is on file. Ask for a bridge letter and file it against the vendor.",
            f"/vendors?vendor={vendor.id}&tab=assessments", report.expires_at,
        ))
    returned = QuestionnaireInvite.objects.filter(
        submitted_at__isnull=False, assessment__isnull=False,
        assessment__result=VendorAssessment.Result.PENDING,
    ).select_related("vendor", "assessment")
    lapsed = QuestionnaireInvite.objects.filter(
        submitted_at__isnull=True, revoked_at__isnull=True, expires_at__lt=timezone.now(),
        expires_at__gte=timezone.now() - timezone.timedelta(days=30),
    ).select_related("vendor")
    if not can_prompt:
        returned = returned.filter(vendor__owner=user)
        lapsed = lapsed.filter(vendor__owner=user)
    for inv in returned:
        answered = sum(1 for a in (inv.assessment.answers or {}).values() if a.get("answer"))
        items.append(_n(
            f"vendor-questionnaire:{inv.assessment_id}", "vendor", "medium",
            f"Questionnaire returned by {inv.vendor.name}",
            f"{inv.respondent_name or inv.sent_to} answered {count_of(answered, 'question')} on "
            f"{inv.submitted_at.date().isoformat()}. Review the answers and record the outcome.",
            f"/vendors?vendor={inv.vendor_id}&tab=questionnaire", inv.submitted_at.date(),
        ))
    for inv in lapsed:
        items.append(_n(
            f"vendor-questionnaire-lapsed:{inv.id}", "vendor", "low",
            f"Questionnaire unanswered by {inv.vendor.name}",
            f"The link sent to {inv.sent_to} expired on {inv.expires_at.date().isoformat()} "
            f"{'after being opened' if inv.opened_at else 'without being opened'}. Send it again or chase them.",
            f"/vendors?vendor={inv.vendor_id}&tab=questionnaire", inv.expires_at.date(),
        ))
    return items


def _risk_items(user, today):
    from governance.models import Risk

    items = []
    my_risks = Risk.objects.filter(
        owner=user, status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING]
    ).select_related("control")
    for r in my_risks:
        if r.due_date and r.due_date < today:
            items.append(_n(
                f"risk-overdue:{r.id}", "risk", "high",
                f"Risk remediation overdue: {r.title}",
                f"{r.rating.title()} ({r.score}) · due {r.due_date.isoformat()}",
                "/risks", r.due_date,
            ))
        elif r.rating in ("critical", "high"):
            items.append(_n(
                f"risk-high:{r.id}", "risk", "medium",
                f"{r.rating.title()} risk assigned to you: {r.title}",
                f"Score {r.score}" + (f" · due {r.due_date.isoformat()}" if r.due_date else ""),
                "/risks", r.due_date,
            ))
    return items


def _event_items(user, today):
    from calendar_app.models import CalendarEvent

    items = []
    my_events = CalendarEvent.objects.filter(assignee=user, completed=False)
    for e in my_events:
        days = (e.date - today).days
        if days < 0:
            items.append(_n(
                f"event-overdue:{e.id}", "event", "high",
                f"Task overdue: {e.title}",
                f"Was due {e.date.isoformat()}", "/", e.date,
            ))
        elif days <= 7:
            items.append(_n(
                f"event-soon:{e.id}", "event", "low",
                f"Upcoming: {e.title}",
                f"{e.date.isoformat()} ({days}d)", "/", e.date,
            ))
    return items


def _meeting_items(user, today):
    import math

    from governance.models import MeetingMinute, MeetingSeries

    items = []
    for series in MeetingSeries.objects.filter(owner=user, active=True):
        held = MeetingMinute.objects.filter(series=series, date__year=today.year).count()
        expected = min(series.required_per_year, math.ceil(series.required_per_year * today.month / 12))
        if held < expected:
            items.append(_n(
                f"meeting-behind:{series.id}", "meeting", "medium",
                f"Meeting cadence behind: {series.name}",
                f"{held} of {series.required_per_year} held this year (expected {expected})",
                "/meetings", today,
            ))
    return items


def _scanner_items(user, today):
    items = []
    if getattr(user, "can_manage_users", False) or getattr(user, "can_manage_frameworks", False):
        from documents import monitor
        state = monitor.probe()
        if state["enabled"] and state["reachable"] is False:
            since = state["down_since"]
            items.append(_n(
                "scanner-down", "system", "critical",
                "Malware scanner unreachable: uploads are being refused",
                f"clamd has not answered since {since.isoformat(timespec='minutes') if since else 'the last check'}. "
                "Evidence cannot be filed until it is back.",
                "/documents", today,
            ))
        held = monitor.quarantined().count()
        if held:
            items.append(_n(
                "digest-quarantined", "system", "high",
                f"{held} document{'s' if held != 1 else ''} in quarantine",
                "The scanner matched a signature on a stored file; it cannot be opened until "
                "a re-scan clears it or it is deleted.", "/documents", today,
            ))
    return items


def _register_digest_items(user, today):
    from compliance.models import Control
    from django.db.models import Count
    from governance.models import Risk

    items = []
    if getattr(user, "can_manage_frameworks", False):
        overdue_risks = Risk.objects.filter(
            status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING], due_date__lt=today
        ).count()
        if overdue_risks:
            items.append(_n(
                "digest-risks-overdue", "risk", "high",
                f"{overdue_risks} risk{'s' if overdue_risks != 1 else ''} overdue across the register",
                "Remediation past its target date", "/risks", today,
            ))
        no_eu = Control.objects.annotate(n=Count("evidence_links")).filter(n=0).count()
        if no_eu:
            items.append(_n(
                "digest-evidence-gap", "evidence", "low",
                f"{no_eu} control{'s' if no_eu != 1 else ''} have no evidence linked",
                "Attach documents to close coverage gaps", "/controls", today,
            ))
    return items


def _document_backlog_items(user, today):
    from documents.models import Document

    items = []
    if getattr(user, "can_manage_documents", False) or getattr(user, "can_view_all", False):
        org_overdue = (
            Document.objects.filter(next_review_date__lt=today)
            .exclude(owner=user).count()
        )
        if org_overdue:
            items.append(_n(
                "digest-docs-overdue", "doc_review", "medium",
                f"{org_overdue} document{'s' if org_overdue != 1 else ''} overdue for review org-wide",
                "Owned by other team members", "/documents", today,
            ))
    return items


def _pbc_items(user, today):
    from attestations import access as package_access
    from attestations.models import EvidencePackage, PbcRequest

    items = []
    mine = PbcRequest.objects.filter(
        assignee=user, status__in=PbcRequest.ACTIONABLE,
    ).exclude(package__status=EvidencePackage.Status.WITHDRAWN).select_related("package")
    for r in mine:
        if r.status == PbcRequest.Status.RETURNED:
            items.append(_n(
                f"pbc-returned:{r.id}", "pbc", "high",
                f"Returned by the auditor: {r.reference} {r.title}",
                (r.returned_note or "Needs more")[:160] + f" · {r.package.name}",
                "/packages", r.returned_at.date() if r.returned_at else today,
            ))
            continue
        if r.due_date and r.due_date < today:
            items.append(_n(
                f"pbc-overdue:{r.id}", "pbc", "high",
                f"Auditor request overdue: {r.reference} {r.title}",
                f"Was due {r.due_date.isoformat()} ({(today - r.due_date).days}d ago) · {r.package.name}",
                "/packages", r.due_date,
            ))
        elif r.due_date and (r.due_date - today).days <= 7:
            items.append(_n(
                f"pbc-due:{r.id}", "pbc", "medium",
                f"Auditor request due soon: {r.reference} {r.title}",
                f"Due {r.due_date.isoformat()} ({(r.due_date - today).days}d) · {r.package.name}",
                "/packages", r.due_date,
            ))
    if getattr(user, "can_manage_frameworks", False):
        org_overdue = PbcRequest.objects.filter(
            status__in=PbcRequest.ACTIONABLE, due_date__lt=today,
        ).exclude(package__status=EvidencePackage.Status.WITHDRAWN).exclude(assignee=user).count()
        if org_overdue:
            items.append(_n(
                "digest-pbc-overdue", "pbc", "high",
                f"{org_overdue} auditor request{'s' if org_overdue != 1 else ''} overdue",
                "Assigned to other people, past their due date", "/packages", today,
            ))
        unassigned = PbcRequest.objects.filter(
            status__in=PbcRequest.ACTIONABLE, assignee__isnull=True,
        ).exclude(package__status=EvidencePackage.Status.WITHDRAWN).count()
        if unassigned:
            items.append(_n(
                "digest-pbc-unassigned", "pbc", "medium",
                f"{unassigned} auditor request{'s' if unassigned != 1 else ''} nobody owns yet",
                "Assign each one so it gets chased", "/packages", today,
            ))
    if getattr(user, "is_auditor", False):
        for pkg in package_access.readable_packages(user):
            waiting = pkg.pbc_requests.filter(status=PbcRequest.Status.PROVIDED).count()
            if waiting:
                items.append(_n(
                    f"pbc-awaiting:{pkg.id}", "pbc", "medium",
                    f"{waiting} answer{'s' if waiting != 1 else ''} to review in {pkg.name}",
                    "Provided by the organisation; accept or return each one", "/packages", today,
                ))
    return items


def _access_review_items(user, today):
    from governance.models import AccessReview, AccessReviewItem

    items = []
    is_admin = getattr(user, "can_manage_users", False)
    is_auditor = getattr(user, "is_auditor", False)
    if is_admin or is_auditor:
        for review in AccessReview.objects.filter(status=AccessReview.Status.OPEN):
            pending = review.items.filter(decision=AccessReviewItem.Decision.PENDING).count()
            if is_admin:
                items.append(_n(
                    f"access-review:{review.id}", "access_review", "medium",
                    f"Access review open: {review.name}",
                    f"{pending} decision{'s' if pending != 1 else ''} pending",
                    "/user-audit", today,
                ))
            else:
                items.append(_n(
                    f"access-review-audit:{review.id}", "access_review", "info",
                    f"Access review in progress: {review.name}",
                    f"{pending} decision{'s' if pending != 1 else ''} pending",
                    "/user-audit", today,
                ))
    return items


def build(user):
    from django.utils import timezone

    today = timezone.localdate()
    items = []
    for section in (
        _document_items, _vendor_items, _risk_items, _event_items, _meeting_items, _scanner_items,
        _register_digest_items, _document_backlog_items, _pbc_items, _access_review_items,
    ):
        items += section(user, today)
    items.sort(key=lambda i: (SEVERITY_RANK.get(i["severity"], 9), i["as_of"] or ""))
    return items[:MAX_ITEMS]
