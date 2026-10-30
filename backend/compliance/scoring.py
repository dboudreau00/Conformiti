"""Per-control readiness, not the share marked implemented. Evidence and freshness count only links the caller can
see: an org-wide figure given to a folder-restricted auditor would reveal hidden evidence."""
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
    # Not "Not started"/"Not applicable": Control.status uses those words and the two sit side by side on a row.
    "not_started": "Not ready",
    "at_risk": "At risk",
    "nearly": "Nearly there",
    "ready": "Ready",
    "not_applicable": "Excluded",
}


def weights():
    """Read at call time, never at import, so ``@override_settings`` works; a partial override is merged in."""
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


def annotate(queryset, user, visible=None):
    """Add every score signal in one query; evidence counts only folders ``user`` can see, or ``visible`` when given.
    Annotate any queryset whose serializer reports a score, or each row falls back to its own query."""
    from documents.access import accessible_folder_ids

    visible = accessible_folder_ids(user) if visible is None else visible
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
        accountable_rows=Count(
            "responsibilities",
            filter=Q(responsibilities__role="accountable"),
            distinct=True,
        ),
    )


def programme_score(queryset=None):
    """Organisation readiness, counting evidence in every folder: ``{"score", "applicable", "bands", "by_framework"}``.
    ``score`` is None when nothing applies; a framework with nothing applicable has no ``by_framework`` entry."""
    from django.db.models import F

    from documents.models import Folder

    from .models import Control

    qs = queryset if queryset is not None else Control.objects.all()
    qs = annotate(qs.exclude(status="not_applicable"), None,
                  visible=set(Folder.objects.values_list("id", flat=True)))
    qs = qs.annotate(fw_id=F("category__framework_id"))
    counts = {"ready": 0, "nearly": 0, "at_risk": 0, "not_started": 0}
    total = 0
    n = 0
    per_framework = {}
    for control in qs:
        result = score_control(control)
        if result["score"] is None:
            continue
        total += result["score"]
        n += 1
        counts[result["band"]] = counts.get(result["band"], 0) + 1
        fw = per_framework.setdefault(
            control.fw_id, {"total": 0, "n": 0, "bands": dict.fromkeys(counts, 0)})
        fw["total"] += result["score"]
        fw["n"] += 1
        fw["bands"][result["band"]] = fw["bands"].get(result["band"], 0) + 1
    return {
        "score": round(total / n) if n else None,
        "applicable": n,
        "bands": counts,
        "by_framework": {
            fw_id: {"score": round(fw["total"] / fw["n"]), "applicable": fw["n"], "bands": fw["bands"]}
            for fw_id, fw in per_framework.items()
        },
    }


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
    # Binary on purpose: a link count is trivially gamed.
    if total:
        return 1.0, f"{total} document(s) linked as evidence."
    return 0.0, "No evidence linked."


def _freshness(total, approved, best_review, weight, today, fresh_days):
    if not total:
        return 0.0, "No evidence to age."
    if not approved:
        return 0.0, f"{total} document(s) linked but none are approved."
    if best_review is None:
        # Zero, not partial: a "none" review cadence leaves next_review_date null, and that must not score well.
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
    """Score and breakdown. An unannotated row costs per-row queries, scoped to ``user`` (all folders if None)."""
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

    # Round once, at the end: rounding each component first breaks "doubling every weight changes nothing".
    earned = sum(w[key] * factor for key, factor, _ in factors)
    possible = sum(w[key] for key in EARNING)
    penalty = w["risk_penalty"] * min(1.0, 0.5 * open_risks)
    score = 0 if possible <= 0 else max(0, min(100, round(100 * (earned - penalty) / possible)))

    components = [
        {
            "key": key,
            "label": key.replace("_", " ").capitalize(),
            "weight": w[key],
            # Display only: the score is not summed from these.
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
    """The action worth the most points still on the table; an open risk comes first."""
    if open_risks:
        return "Close or accept the open risk against this control."
    gaps = [(w[key] * (1.0 - factor), key) for key, factor, _ in factors if factor < 1.0]
    if not gaps:
        return None
    order = {key: i for i, key in enumerate(EARNING)}
    gaps.sort(key=lambda g: (-g[0], order[g[1]]))
    return ACTIONS[gaps[0][1]]
