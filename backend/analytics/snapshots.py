"""Record and read readiness history."""
import logging

from django.db import DatabaseError, transaction
from django.db.models import Count
from django.utils import timezone

from compliance.models import Control, ControlEvidence
from documents.models import Document
from governance.models import Risk

from .models import ReadinessSnapshot

logger = logging.getLogger(__name__)
TREND_MONTHS = 6


def _measure():
    from compliance.scoring import programme_score

    by_status = {row["status"]: row["n"] for row in Control.objects.values("status").annotate(n=Count("id"))}
    total = sum(by_status.values())
    not_applicable = by_status.get("not_applicable", 0)
    today = timezone.localdate()
    return {
        "total_controls": total,
        "applicable": total - not_applicable,
        "implemented": by_status.get("implemented", 0),
        "in_progress": by_status.get("in_progress", 0),
        "with_evidence": Control.objects.annotate(n=Count("evidence_links")).filter(n__gt=0).count(),
        "evidence_links": ControlEvidence.objects.count(),
        "documents_overdue": Document.objects.filter(next_review_date__lt=today).count(),
        "risks_open": Risk.objects.filter(status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING]).count(),
        "score": programme_score()["score"],
    }


def record_today(force=False):
    """Create (or, with force, refresh) today's snapshot. Idempotent; never
    raises — a read replica or a locked table must not break the dashboard."""
    today = timezone.localdate()
    try:
        with transaction.atomic():
            snap, created = ReadinessSnapshot.objects.get_or_create(date=today, defaults=_measure())
            if not created and force:
                for k, v in _measure().items():
                    setattr(snap, k, v)
                snap.save()
            return snap
    except DatabaseError:
        logger.exception("Could not record readiness snapshot")
        return None


def trend(months=TREND_MONTHS):
    """Monthly series ending this month: the last snapshot of each of the
    last ``months`` calendar months, plus the delta (percentage points) between
    the latest point and the one before it. Months with no snapshot are
    omitted — a fresh install shows one point, not invented history."""
    today = timezone.localdate()
    first_month = today.replace(day=1)
    for _ in range(months - 1):
        first_month = (first_month - timezone.timedelta(days=1)).replace(day=1)
    points = []
    seen = {}
    for snap in ReadinessSnapshot.objects.filter(date__gte=first_month).order_by("date"):
        seen[(snap.date.year, snap.date.month)] = snap  # last one per month wins
    for (year, month), snap in sorted(seen.items()):
        points.append({
            "label": snap.date.strftime("%b"),
            "month": f"{year:04d}-{month:02d}",
            "date": snap.date.isoformat(),
            "pct": snap.pct,
            "score": snap.score,
            "implemented": snap.implemented,
            "applicable": snap.applicable,
        })
    delta = points[-1]["pct"] - points[-2]["pct"] if len(points) >= 2 else None
    # The score is the headline figure from 0.9.5 on. Its own delta is only
    # offered when both months measured it; before that the implemented
    # share is the only history there is, and the dashboard says which it is
    # showing.
    scored = [p for p in points if p["score"] is not None]
    score_delta = (scored[-1]["score"] - scored[-2]["score"]
                   if len(scored) >= 2 and scored[-1] is points[-1] else None)
    return {"points": points, "delta_pts": delta, "score_delta_pts": score_delta}
