"""
Per-control readiness: how ready a control actually is, not whether someone
ticked "implemented".

Until 0.3.0 readiness was ``implemented / applicable``. A control counted as
implemented with no owner, no evidence, evidence that expired two years ago and
an open control gap against it — which is exactly the state an auditor finds
and the dashboard did not.

Six signals, five of which earn and one of which subtracts:

===============  ======  ===========================================
signal           weight  what it answers
===============  ======  ===========================================
implementation   35      has the work been done?
owner            10      is anyone accountable for it?
evidence         20      is there anything to show?
freshness        20      is what we would show still current?
testing          15      has anyone checked that it works?
risk_penalty     20 (-)  do we already know it is failing?
===============  ======  ===========================================

Weights need not sum to 100: the score is normalised over the five that earn,
so doubling every weight leaves every score unchanged. With the defaults
``possible == 100``, so a point reads as a percentage point and the breakdown
is directly legible.

**Everything here is folder-aware.** The evidence and freshness components are
computed from the links the *caller* can see. An org-wide per-control integer
handed to a folder-restricted external auditor is losslessly invertible: with
the other four signals visible, the pair (evidence, freshness) maps injectively
onto "does hidden evidence exist, is it approved, how fresh is it".
"""
from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

DEFAULT_WEIGHTS = {
    "implementation": 35,
    "owner": 10,
    "evidence": 20,
    "freshness": 20,
    "testing": 15,
    "risk_penalty": 20,
}
EARNING = ["implementation", "owner", "evidence", "freshness", "testing"]

BAND_LABELS = {
    # Deliberately not "Not started"/"Not applicable": Control.status already
    # uses those words, and the two would sit side by side on the same row.
    # "Unscored" would be worse still -- a control in this band has a score,
    # it is just a low one.
    "not_started": "Not ready",
    "at_risk": "At risk",
    "nearly": "Nearly there",
    "ready": "Ready",
    "not_applicable": "Excluded",
}


def weights():
    """Merged over the defaults, so a partial override is legal.

    Read at call time, never captured at import, so ``@override_settings``
    works in tests.
    """
    return {**DEFAULT_WEIGHTS, **(getattr(settings, "READINESS_WEIGHTS", None) or {})}


def bands():
    return list(getattr(settings, "READINESS_BANDS", [40, 70, 90]))


def band_for(score):
    if score is None:
        return "not_applicable"
    at_risk, nearly, ready = bands()
    if score >= ready:
        return "ready"
    if score >= nearly:
        return "nearly"
    if score >= at_risk:
        return "at_risk"
    return "not_started"


def annotate(queryset, user):
    """Add every signal the score needs, in one query.

    ``evidence`` and ``freshness`` count only documents in folders ``user`` can
    see. Call this on any queryset whose serializer will report a score, or the
    serializer falls back to a per-row query.
    """
    from documents.access import accessible_folder_ids

    visible = accessible_folder_ids(user)
    visible_link = Q(evidence_links__document__folder_id__in=visible)
    approved_link = visible_link & Q(evidence_links__document__status="approved")
    return queryset.annotate(
        ev_total=Count("evidence_links", filter=visible_link, distinct=True),
        ev_approved=Count("evidence_links", filter=approved_link, distinct=True),
        ev_best_review=Max("evidence_links__document__next_review_date", filter=approved_link),
        open_risks=Count(
            "risks",
            filter=Q(risks__status__in=("open", "mitigating")),
            distinct=True,
        ),
        # An explicit Accountable row in the responsibility matrix satisfies
        # the owner signal just as Control.owner does.
        accountable_rows=Count(
            "responsibilities",
            filter=Q(responsibilities__role="accountable"),
            distinct=True,
        ),
    )


def _implementation(control, weight):
    factor = {"implemented": 1.0, "in_progress": 0.4}.get(control.status, 0.0)
    detail = {
        "implemented": "Marked implemented.",
        "in_progress": "Implementation in progress.",
    }.get(control.status, "Not started.")
    return factor, detail


def _owner(control, weight):
    if control.owner_id:
        return 1.0, "Has an accountable owner."
    accountable = getattr(control, "accountable_rows", None)
    if accountable is None:
        accountable = control.responsibilities.filter(role="accountable").count()
    if accountable:
        return 1.0, "Accountable party named in the responsibility matrix."
    return 0.0, "No owner assigned."


def _evidence(total, weight):
    # Deliberately binary. A link count is trivially gamed, and an auditor asks
    # whether there is evidence, not how many files there are.
    if total:
        return 1.0, f"{total} document(s) linked as evidence."
    return 0.0, "No evidence linked."


def _freshness(total, approved, best_review, weight, today, fresh_days):
    if not total:
        return 0.0, "No evidence to age."
    if not approved:
        return 0.0, f"{total} document(s) linked but none are approved."
    if best_review is None:
        # Deliberately zero, not half. Document.review_cadence accepts "none",
        # which leaves next_review_date null -- so awarding half the weight in
        # perpetuity would make the one document nobody will ever chase the
        # best-scoring evidence you can attach.
        return 0.0, "Approved evidence has no review schedule."
    days = (best_review - today).days
    if days >= fresh_days:
        return 1.0, f"Freshest approved evidence is current (next review in {days} days)."
    if days >= 0:
        return 0.75, f"Freshest approved evidence is due in {days} days."
    if days >= -fresh_days:
        return 0.4, f"Freshest approved evidence was due {-days} days ago."
    return 0.0, f"Freshest approved evidence is {-days} days overdue."


def _testing(control, weight, today, default_interval):
    if not control.last_tested_on:
        return 0.0, "Never tested."
    interval = control.test_interval_days or default_interval
    if interval <= 0:
        interval = default_interval
    age = max(0, (today - control.last_tested_on).days)
    if age <= interval:
        return 1.0, f"Tested {age} days ago (interval {interval} days)."
    if age <= interval * 3 // 2:
        return 0.5, f"Test is {age - interval} days past its {interval}-day interval."
    return 0.0, f"Last tested {age} days ago, well past its {interval}-day interval."


def score_control(control, user=None):
    """The score and its full breakdown.

    Uses the annotations from :func:`annotate` when present, and falls back to
    per-row queries otherwise so a caller that forgot still gets the right
    answer — just more slowly.
    """
    if control.status == "not_applicable":
        return {
            "score": None,
            "band": "not_applicable",
            "band_label": BAND_LABELS["not_applicable"],
            "components": [],
            "penalty": 0,
            "next_best_action": None,
        }

    w = weights()
    today = timezone.localdate()
    fresh_days = getattr(settings, "READINESS_FRESH_DAYS", 30)
    default_interval = getattr(settings, "CONTROL_TEST_INTERVAL_DAYS", 365)

    total, approved, best_review, open_risks = _signals(control, user)

    factors = [
        ("implementation", *_implementation(control, w["implementation"])),
        ("owner", *_owner(control, w["owner"])),
        ("evidence", *_evidence(total, w["evidence"])),
        ("freshness", *_freshness(total, approved, best_review, w["freshness"], today, fresh_days)),
        ("testing", *_testing(control, w["testing"], today, default_interval)),
    ]

    # Accumulate exact fractions and round ONCE. Rounding each component before
    # summing breaks the "doubling every weight changes nothing" invariant.
    earned = sum(w[key] * factor for key, factor, _ in factors)
    possible = sum(w[key] for key in EARNING)
    penalty = w["risk_penalty"] * min(1.0, 0.5 * open_risks)
    score = 0 if possible <= 0 else max(0, min(100, round(100 * (earned - penalty) / possible)))

    components = [
        {
            "key": key,
            "label": key.replace("_", " ").capitalize(),
            "weight": w[key],
            # Display points only; the score above does not use these.
            "points": round(w[key] * factor),
            "earned": factor >= 1.0,
            "detail": detail,
        }
        for key, factor, detail in factors
    ]
    band = band_for(score)
    return {
        "score": score,
        "band": band,
        "band_label": BAND_LABELS[band],
        "components": components,
        "penalty": round(penalty),
        "open_risks": open_risks,
        "next_best_action": _next_action(factors, open_risks, w),
    }


def _signals(control, user):
    """(links, approved links, freshest approved review date, open risks)."""
    total = getattr(control, "ev_total", None)
    if total is not None:
        return (
            total,
            getattr(control, "ev_approved", 0),
            getattr(control, "ev_best_review", None),
            getattr(control, "open_risks", 0),
        )
    # Fallback: the caller did not annotate. Still folder-scoped.
    from documents.access import accessible_folder_ids

    links = control.evidence_links.all()
    if user is not None:
        links = links.filter(document__folder_id__in=accessible_folder_ids(user))
    approved = links.filter(document__status="approved")
    return (
        links.count(),
        approved.count(),
        approved.aggregate(m=Max("document__next_review_date"))["m"],
        control.risks.filter(status__in=("open", "mitigating")).count(),
    )


ACTIONS = {
    "implementation": "Finish implementing the control and mark it implemented.",
    "owner": "Assign an owner.",
    "evidence": "Link a document as evidence.",
    "freshness": "Approve the evidence and give it a current review date.",
    "testing": "Record a test date for this control.",
}


def _next_action(factors, open_risks, w):
    """The single change that would move this control's score the most.

    Ranked by points still on the table, not by position in the list: a control
    missing 15 points of testing and 5 of freshness should be told to record a
    test, not to tidy the review date.
    """
    if open_risks:
        return "Close or accept the open risk against this control."
    gaps = [(w[key] * (1.0 - factor), key) for key, factor, _ in factors if factor < 1.0]
    if not gaps:
        return None
    # Ties break on the fixed component order, so the answer is deterministic.
    order = {key: i for i, key in enumerate(EARNING)}
    gaps.sort(key=lambda g: (-g[0], order[g[1]]))
    return ACTIONS[gaps[0][1]]
