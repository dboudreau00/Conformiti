"""
Derived, per-user notifications.

Notifications aren't a static table that a job fills in — they're computed for
the requesting user from the things *they* are responsible for. What each
person sees is therefore a function of two "assigned parameters":

  1. Ownership / assignment — documents they own, risks they own, calendar
     events assigned to them, meeting series they run.
  2. Role capability — managers get org-wide digests (overdue risks, evidence
     gaps, review backlog); admins get access-review and user items; auditors
     get read-only review pointers.

Each item has a stable ``key`` so read/dismissed state (NotificationReceipt)
survives recomputation. Severity drives ordering and the unread badge.
"""

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


def build(user):
    """Return the personalized notification list for ``user`` (unsorted state
    like read/dismissed is applied by the view)."""
    # Imported lazily so notifications never participates in app-load ordering
    # and this module stays importable (for tests) without Django configured.
    from django.db.models import Count
    from django.utils import timezone
    from documents.models import Document
    from governance.models import (
        AccessReview, AccessReviewItem, MeetingMinute, MeetingSeries, Risk,
    )
    from calendar_app.models import CalendarEvent
    from compliance.models import Control

    today = timezone.localdate()
    items = []

    # ---- 1. Documents I own -------------------------------------------------
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

    # ---- 1b. Vendors I own --------------------------------------------------
    from vendors.models import Vendor, VendorAssessment
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
    # Onboarding prompt: a new or unstated vendor needs its responsibility
    # matrix before an auditor asks which controls' evidence to expect from
    # whom. Surfaced to the vendor's owner and to every frameworks manager.
    from vendors.models import SharedResponsibility
    from vendors.assurance import bridge_letter_gaps
    from compliance.models import Control
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
    # A SOC report whose period has ended, with no newer report and no bridge
    # letter covering the gap: the auditor will ask for the letter, so ask the
    # vendor first. Owner and frameworks managers alike.
    for vendor, report in bridge_letter_gaps(user):
        items.append(_n(
            f"vendor-bridge:{vendor.id}", "vendor",
            "high" if vendor.tier in ("critical", "high") else "medium",
            f"Bridge letter needed from {vendor.name}",
            f"{report.get_kind_display()} lapsed on {report.expires_at.isoformat()} and nothing "
            "newer is on file. Ask for a bridge letter and file it against the vendor.",
            f"/vendors?vendor={vendor.id}&tab=assessments", report.expires_at,
        ))
    # A questionnaire the vendor answered through the emailed link is waiting
    # for someone here to read it; and a link that expired unanswered needs
    # chasing. Owner and frameworks managers.
    from vendors.models import QuestionnaireInvite
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
            f"{inv.respondent_name or inv.sent_to} answered {answered} question(s) on "
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

    # ---- 2. Risks I own -----------------------------------------------------
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

    # ---- 3. Calendar events assigned to me ----------------------------------
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

    # ---- 4. Meeting series I own that are behind cadence --------------------
    import math
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

    caps = user  # capability flags live on the user

    # ---- 5. Manager digest: org-wide risk + evidence posture ----------------
    if getattr(caps, "can_manage_frameworks", False):
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

    # ---- 6. Manager digest: org-wide review backlog (docs I don't own) ------
    if getattr(caps, "can_manage_documents", False) or getattr(caps, "can_view_all", False):
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

    # ---- 6b. PBC requests: what I owe the auditor, and what the auditor is
    # waiting on. The assignee is chased; managers get the org-wide gaps; the
    # issued auditor sees what has been provided since they last looked.
    from attestations import access as package_access
    from attestations.models import EvidencePackage, PbcRequest
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
    if getattr(caps, "can_manage_frameworks", False):
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
    if getattr(caps, "is_auditor", False):
        for pkg in package_access.readable_packages(user):
            waiting = pkg.pbc_requests.filter(status=PbcRequest.Status.PROVIDED).count()
            if waiting:
                items.append(_n(
                    f"pbc-awaiting:{pkg.id}", "pbc", "medium",
                    f"{waiting} answer{'s' if waiting != 1 else ''} to review in {pkg.name}",
                    "Provided by the organisation; accept or return each one", "/packages", today,
                ))

    # ---- 7. Access reviews (admins act; auditors observe) -------------------
    is_admin = getattr(caps, "can_manage_users", False)
    is_auditor = getattr(caps, "is_auditor", False)
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
            else:  # auditor — informational pointer
                items.append(_n(
                    f"access-review-audit:{review.id}", "access_review", "info",
                    f"Access review in progress: {review.name}",
                    f"{pending} decision{'s' if pending != 1 else ''} pending",
                    "/user-audit", today,
                ))

    # newest / most severe first, then cap
    items.sort(key=lambda i: (SEVERITY_RANK.get(i["severity"], 9), i["as_of"] or ""))
    return items[:MAX_ITEMS]
