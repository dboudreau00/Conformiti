"""
Analytics aggregation.

A single read-only endpoint, ``GET /api/analytics/summary/``, returns the numbers
the dashboards need in one round trip:

  * per-framework control implementation and status breakdown
  * organisation-wide control status, ownership and evidence coverage
  * readiness history (monthly trend + month-over-month delta)
  * document status + ownership (restricted to folders the caller may see)
  * review posture: overdue / due-soon buckets and a six-month timeline
  * a small sample of the most overdue documents

Framework/control figures are organisation-wide (matching the dashboard, where
every user sees overall program progress). Document figures are filtered to the
caller's visible folders so nothing leaks past folder-level RBAC.
"""
from dateutil.relativedelta import relativedelta
from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import NotExternalAuditor
from compliance.models import Control, ControlEvidence, Framework
from governance.models import Risk
from documents.access import accessible_folder_ids
from documents.models import Document
from documents.serializers import person_name

from .snapshots import record_today, trend

CONTROL_STATUSES = ["not_started", "in_progress", "implemented", "not_applicable"]
DOC_STATUSES = ["draft", "in_review", "approved", "expired"]


def _counts_by(qs, field, keys):
    """Return a dict of {key: count} for `field`, with every key present (0-filled)."""
    base = {k: 0 for k in keys}
    for row in qs.values(field).annotate(n=Count("id")):
        base[row[field]] = row["n"]
    return base


class AnalyticsSummaryView(APIView):
    # Readiness, coverage and ownership for the whole organisation: the
    # programme, not the engagement.
    permission_classes = [IsAuthenticated, NotExternalAuditor]

    def get(self, request):
        from compliance.scoring import programme_score

        today = timezone.localdate()

        # Scored once, up front: the headline, the bands and every framework's
        # row of the lead schedule come out of this one pass, and the snapshot
        # below reuses it instead of scoring every control a second time.
        scored = programme_score()

        # --- Controls (organisation-wide) -----------------------------------
        control_status = _counts_by(Control.objects.all(), "status", CONTROL_STATUSES)
        total_controls = sum(control_status.values())
        owned_controls = Control.objects.filter(owner__isnull=False).count()
        applicable_all = total_controls - control_status["not_applicable"]

        # Evidence coverage (organisation-wide aggregates only — counts, no titles,
        # consistent with the org-wide control figures above). Grouped by
        # framework in one query; the programme figure is their sum, so the
        # schedule's column foots to the dashboard's coverage card.
        evidence_by_framework = {
            row["category__framework_id"]: row["n"]
            for row in (Control.objects.filter(evidence_links__isnull=False)
                        .values("category__framework_id")
                        .annotate(n=Count("id", distinct=True)))
        }
        controls_with_evidence = sum(evidence_by_framework.values())
        evidence_links_total = ControlEvidence.objects.count()

        # Risk posture (org-wide aggregate, like the control figures).
        live_risks = Risk.objects.filter(
            status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING]
        )
        risks_block = {
            "open": live_risks.count(),
            "overdue": live_risks.filter(due_date__lt=today).count(),
            "mitigating": live_risks.filter(status=Risk.Status.MITIGATING).count(),
            "accepted": Risk.objects.filter(status=Risk.Status.ACCEPTED).count(),
        }

        # One grouped query for every framework's status counts, so the cost of
        # this block does not grow with the number of frameworks installed.
        status_by_framework = {}
        for row in Control.objects.values("category__framework_id", "status").annotate(n=Count("id")):
            status_by_framework.setdefault(row["category__framework_id"], {})[row["status"]] = row["n"]

        frameworks = []
        for fw in Framework.objects.all().order_by("name", "key", "id"):
            by_status = {k: status_by_framework.get(fw.id, {}).get(k, 0) for k in CONTROL_STATUSES}
            total = sum(by_status.values())
            implemented = by_status["implemented"]
            # Applicable = everything except explicitly N/A.
            applicable = total - by_status["not_applicable"]
            pct = round(implemented / applicable * 100) if applicable else 0
            # `score` is the framework's own readiness (the mean score of its
            # applicable controls, as the headline is for the programme); `pct`
            # stays the implemented share. Null when nothing is applicable.
            fw_scored = scored["by_framework"].get(fw.id)
            frameworks.append({
                "id": fw.id,
                "key": fw.key,
                "name": fw.name,
                "version": getattr(fw, "version", ""),
                "total": total,
                "implemented": implemented,
                "applicable": applicable,
                "pct": pct,
                "by_status": by_status,
                "with_evidence": evidence_by_framework.get(fw.id, 0),
                "score": fw_scored["score"] if fw_scored else None,
                "bands": fw_scored["bands"] if fw_scored else
                {"ready": 0, "nearly": 0, "at_risk": 0, "not_started": 0},
            })

        # --- Readiness history -----------------------------------------------
        record_today(scored=scored)  # idempotent: first hit of the day records a point
        history = trend()
        # `pct` is the share of applicable controls marked implemented — the
        # figure this endpoint has always reported and the one the trend
        # history is made of. `score` is what the register scores a control
        # on: implementation, an owner, evidence, its freshness, a test, less
        # open risks. A control marked implemented with none of the rest used
        # to count as ready here and score poorly one page over; the dashboard
        # now leads with the score and shows the share beside it.
        readiness = {
            "pct": round(control_status["implemented"] / applicable_all * 100) if applicable_all else 0,
            "implemented": control_status["implemented"],
            "applicable": applicable_all,
            "score": scored["score"],
            "bands": scored["bands"],
            "delta_pts": history["delta_pts"],
            "score_delta_pts": history.get("score_delta_pts"),
            "trend": history["points"],
        }

        # --- Documents (visible to the caller) ------------------------------
        visible_ids = accessible_folder_ids(request.user)
        docs = Document.objects.filter(folder_id__in=visible_ids)

        doc_status = _counts_by(docs, "status", DOC_STATUSES)
        total_docs = sum(doc_status.values())
        owned_docs = docs.filter(owner__isnull=False).count()

        dated = docs.filter(next_review_date__isnull=False)
        reviews = {
            "overdue": dated.filter(next_review_date__lt=today).count(),
            "due_30": dated.filter(next_review_date__gte=today,
                                   next_review_date__lte=today + relativedelta(days=30)).count(),
            "due_60": dated.filter(next_review_date__gt=today + relativedelta(days=30),
                                   next_review_date__lte=today + relativedelta(days=60)).count(),
            "due_90": dated.filter(next_review_date__gt=today + relativedelta(days=60),
                                   next_review_date__lte=today + relativedelta(days=90)).count(),
            "scheduled": dated.count(),
            "no_schedule": total_docs - dated.count(),
        }

        # Six-month forward timeline of upcoming reviews, bucketed by month.
        timeline = []
        for i in range(6):
            start = (today.replace(day=1) + relativedelta(months=i))
            end = start + relativedelta(months=1)
            count = dated.filter(next_review_date__gte=start,
                                 next_review_date__lt=end).count()
            timeline.append({"month": start.strftime("%b %Y"), "label": start.strftime("%b"), "count": count})

        # Most overdue documents (small sample for the dashboard list).
        overdue_sample = []
        for d in (dated.filter(next_review_date__lt=today)
                  .select_related("owner", "folder")
                  .order_by("next_review_date")[:8]):
            overdue_sample.append({
                "id": d.id,
                "name": d.name,
                "folder_path": d.folder.path if d.folder_id else "",
                "owner": person_name(d.owner) or None,
                "days_overdue": (today - d.next_review_date).days,
            })

        # Risks with an owner (ownership coverage card).
        risk_total = Risk.objects.exclude(status=Risk.Status.CLOSED).count()
        risk_owned = Risk.objects.exclude(status=Risk.Status.CLOSED).filter(owner__isnull=False).count()

        return Response({
            "generated_at": today.isoformat(),
            "frameworks": frameworks,
            "readiness": readiness,
            "controls": {
                "total": total_controls,
                "applicable": applicable_all,
                "by_status": control_status,
                "owned": owned_controls,
                "unowned": total_controls - owned_controls,
                "with_evidence": controls_with_evidence,
                "evidence_links": evidence_links_total,
            },
            "documents": {
                "total": total_docs,
                "by_status": doc_status,
                "owned": owned_docs,
                "unowned": total_docs - owned_docs,
            },
            "risks": {**risks_block, "total_live": risk_total, "owned": risk_owned},
            "reviews": reviews,
            "review_timeline": timeline,
            "overdue_sample": overdue_sample,
        })
