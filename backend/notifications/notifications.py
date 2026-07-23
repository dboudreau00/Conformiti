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
