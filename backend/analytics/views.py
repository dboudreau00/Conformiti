"""
Analytics aggregation.

A single read-only endpoint, ``GET /api/analytics/summary/``, returns the numbers
the analytics dashboard needs in one round trip:

  * per-framework control implementation and status breakdown
  * organisation-wide control status + ownership coverage
  * document status + ownership (restricted to folders the caller may see)
  * review posture: overdue / due-soon buckets and a six-month timeline
  * a small sample of the most overdue documents

Framework/control figures are organisation-wide (matching the dashboard, where
every user sees overall program progress). Document figures are filtered to the
caller's visible folders so nothing leaks past folder-level RBAC.
"""
from datetime import date

from dateutil.relativedelta import relativedelta
from django.db.models import Count
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from compliance.models import Control, ControlEvidence, Framework
from governance.models import Risk
from documents.access import accessible_folder_ids
from documents.models import Document

CONTROL_STATUSES = ["not_started", "in_progress", "implemented", "not_applicable"]
DOC_STATUSES = ["draft", "in_review", "approved", "expired"]


def _counts_by(qs, field, keys):
    """Return a dict of {key: count} for `field`, with every key present (0-filled)."""
    base = {k: 0 for k in keys}
    for row in qs.values(field).annotate(n=Count("id")):
        base[row[field]] = row["n"]
    return base


class AnalyticsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = date.today()

        # --- Controls (organisation-wide) -----------------------------------
        control_status = _counts_by(Control.objects.all(), "status", CONTROL_STATUSES)
        total_controls = sum(control_status.values())
        owned_controls = Control.objects.filter(owner__isnull=False).count()

        # Evidence coverage (organisation-wide aggregates only — counts, no titles,
        # consistent with the org-wide control figures above).
        controls_with_evidence = (
            Control.objects.annotate(n=Count("evidence_links")).filter(n__gt=0).count()
        )
        evidence_links_total = ControlEvidence.objects.count()

        # Risk posture (org-wide aggregate, like the control figures).
        live_risks = Risk.objects.filter(
            status__in=[Risk.Status.OPEN, Risk.Status.MITIGATING]
        )
        risks_block = {
            "open": live_risks.count(),
            "overdue": live_risks.filter(due_date__lt=today).count(),
        }

        frameworks = []
        for fw in Framework.objects.all().order_by("name"):
            fq = Control.objects.filter(category__framework=fw)
            by_status = _counts_by(fq, "status", CONTROL_STATUSES)
            total = sum(by_status.values())
            implemented = by_status["implemented"]
            # Applicable = everything except explicitly N/A.
            applicable = total - by_status["not_applicable"]
            pct = round(implemented / applicable * 100) if applicable else 0
            frameworks.append({
                "key": fw.key,
                "name": fw.name,
                "version": getattr(fw, "version", ""),
                "total": total,
                "implemented": implemented,
                "applicable": applicable,
                "pct": pct,
                "by_status": by_status,
            })

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
            timeline.append({"month": start.strftime("%b %Y"), "count": count})

        # Most overdue documents (small sample for the dashboard list).
        overdue_sample = []
        for d in (dated.filter(next_review_date__lt=today)
                  .select_related("owner", "folder")
                  .order_by("next_review_date")[:8]):
            overdue_sample.append({
                "id": d.id,
                "name": d.name,
                "folder_path": d.folder.path if d.folder_id else "",
                "owner": d.owner.get_full_name() if d.owner else None,
                "days_overdue": (today - d.next_review_date).days,
            })

        return Response({
            "generated_at": today.isoformat(),
            "frameworks": frameworks,
            "controls": {
                "total": total_controls,
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
            "risks": risks_block,
            "reviews": reviews,
            "review_timeline": timeline,
            "overdue_sample": overdue_sample,
        })
