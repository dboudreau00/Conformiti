"""Vendor register API. Readable by every signed-in user (owner and control
pickers need the names); written by the frameworks capability, which is the
one that already governs control ownership."""
import csv

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import CanManageFrameworks

from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from compliance.models import Control

from . import matrix as matrix_lib
from .models import DEFAULT_QUESTIONNAIRE, SharedResponsibility, Vendor, VendorAssessment
from .serializers import (
    SharedResponsibilitySerializer,
    VendorAssessmentSerializer,
    VendorDetailSerializer,
    VendorSerializer,
)

RESPONSIBILITY_VALUES = {c[0] for c in SharedResponsibility.Responsibility.choices}


class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.select_related("owner")
    permission_classes = [CanManageFrameworks]
    filterset_fields = ["tier", "status", "owner", "review_cadence"]
    search_fields = ["name", "category", "data_handled", "services"]
    ordering_fields = ["name", "tier", "next_review_date", "updated_at"]

    def get_queryset(self):
        """The counts the register shows come from annotations, so a page of
        vendors is a handful of queries rather than three per row."""
        from django.db.models import Count, Prefetch, Q

        return (
            Vendor.objects.select_related("owner")
            .annotate(
                n_assessments=Count("assessments", distinct=True),
                n_controls=Count("shared_responsibilities__control", distinct=True),
                n_open_risks=Count("risks", filter=Q(risks__status__in=("open", "mitigating")), distinct=True),
            )
            .prefetch_related(Prefetch(
                "assessments",
                queryset=VendorAssessment.objects.select_related("document", "reviewed_by"),
            ))
        )

    def get_serializer_context(self):
        from documents.access import accessible_folder_ids

        context = super().get_serializer_context()
        # Computed once per request: the nested assessments blank out any
        # document the reader cannot see, and must not recompute this per row.
        context["visible_folders"] = accessible_folder_ids(self.request.user)
        return context

    def get_serializer_class(self):
        return VendorDetailSerializer if self.action == "retrieve" else VendorSerializer

    def perform_create(self, serializer):
        vendor = serializer.save(created_by=self.request.user)
        vendor.compute_next_review()
        vendor.save(update_fields=["next_review_date"])

    def perform_update(self, serializer):
        before = (serializer.instance.review_cadence, serializer.instance.last_reviewed)
        vendor = serializer.save()
        # Only a change to the clock's inputs moves the clock; editing the
        # notes must not push a due review into next year.
        if (vendor.review_cadence, vendor.last_reviewed) != before or not vendor.next_review_date:
            vendor.compute_next_review()
            vendor.save(update_fields=["next_review_date"])

    @action(detail=True, methods=["post"])
    def mark_reviewed(self, request, pk=None):
        """Record a completed periodic review and reset the clock."""
        vendor = self.get_object()
        vendor.last_reviewed = timezone.localdate()
        vendor.compute_next_review()
        vendor.save(update_fields=["last_reviewed", "next_review_date", "updated_at"])
        return Response(VendorSerializer(vendor, context={"request": request}).data)

    # ------------------------------------------------ shared responsibility
    def _controls_for(self, request):
        controls = Control.objects.select_related("category__framework").exclude(
            status="not_applicable")
        framework = request.query_params.get("framework") or request.data.get("framework")
        if framework:
            controls = controls.filter(category__framework__key=framework)
        return controls.order_by("category__framework__name", "category__order", "control_id")

    @action(detail=True, methods=["get"], url_path="matrix")
    def matrix(self, request, pk=None):
        """The in-browser grid: every control in scope with this vendor's
        stated responsibility and statements, blank where nothing has been
        said yet -- so the prompt-through-the-controls flow has somewhere to go."""
        vendor = self.get_object()
        stated = {r.control_id: r for r in SharedResponsibility.objects.filter(vendor=vendor)}
        rows, done = [], 0
        for c in self._controls_for(request):
            r = stated.get(c.pk)
            if r:
                done += 1
            rows.append({
                "control": c.pk, "control_id": c.control_id, "title": c.title,
                "framework": c.category.framework.key, "category": c.category.name,
                "responsibility": r.responsibility if r else None,
                "provider_statement": r.provider_statement if r else "",
                "customer_statement": r.customer_statement if r else "",
                "source": r.source if r else None,
                "updated_at": r.updated_at if r else None,
            })
        return Response({"vendor": vendor.pk, "rows": rows,
                         "summary": {"controls": len(rows), "stated": done,
                                     "unstated": len(rows) - done}})

    @matrix.mapping.put
    def matrix_save(self, request, pk=None):
        """Bulk upsert from the grid or from a confirmed import.

        Body: {"rows": [{"control": id, "responsibility": ..., "provider_statement": ...,
        "customer_statement": ...}], "source": "manual"|"import"}. A row whose
        responsibility is null clears that control. Everything is validated
        before anything is written.
        """
        vendor = self.get_object()
        rows = request.data.get("rows")
        source = "import" if request.data.get("source") == "import" else "manual"
        if not isinstance(rows, list):
            raise ValidationError({"rows": "Send a list of rows."})
        if len(rows) > 2000:
            raise ValidationError({"rows": "Too many rows in one save."})
        valid_ids = set(Control.objects.values_list("pk", flat=True))
        clean, clear = [], []
        for i, row in enumerate(rows):
            try:
                control_id = int(row.get("control"))
            except (TypeError, ValueError, AttributeError):
                raise ValidationError({"rows": f"row {i}: control id is required"})
            if control_id not in valid_ids:
                raise ValidationError({"rows": f"row {i}: unknown control {control_id}"})
            resp = row.get("responsibility")
            if resp in (None, ""):
                clear.append(control_id)
                continue
            if resp not in RESPONSIBILITY_VALUES:
                raise ValidationError({"rows": f"row {i}: responsibility must be one of "
                                                f"{sorted(RESPONSIBILITY_VALUES)}"})
            clean.append((control_id, resp,
                          str(row.get("provider_statement") or "")[:4000],
                          str(row.get("customer_statement") or "")[:4000]))
        layout = None
        if source == "import" and isinstance(request.data.get("layout"), list):
            layout = matrix_lib.clean_layout(
                request.data["layout"], str(request.data.get("layout_name") or "")[:120],
                str(request.data.get("framework") or "")[:40])
        with transaction.atomic():
            if clear:
                SharedResponsibility.objects.filter(vendor=vendor, control_id__in=clear).delete()
            for control_id, resp, ps, cs in clean:
                SharedResponsibility.objects.update_or_create(
                    vendor=vendor, control_id=control_id,
                    defaults={"responsibility": resp, "provider_statement": ps,
                              "customer_statement": cs, "source": source,
                              "updated_by": request.user},
                )
            if layout:
                # Remember how they laid it out, so it can go back the same way.
                vendor.matrix_layout = layout
                vendor.save(update_fields=["matrix_layout", "updated_at"])
        return Response({"saved": len(clean), "cleared": len(clear), "layout_saved": bool(layout)})

    @action(detail=True, methods=["post"], url_path="matrix/parse",
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def matrix_parse(self, request, pk=None):
        """Read the vendor's own matrix file and report what was recognised.

        Writes nothing. The client shows the result, lets the person fix any
        unmatched references or unrecognised responsibilities, then PUTs the
        confirmed rows to ``matrix`` with source "import".
        """
        from governance.risk_import import MAX_FILE_BYTES

        vendor = self.get_object()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Attach a .csv or .xlsx file."})
        # A bare "6.1" is a PCI requirement, an ISO clause and a SOC 2 point
        # of focus; the file is about one of them, and only the person knows.
        if not (request.data.get("framework") or request.query_params.get("framework")):
            raise ValidationError({"framework": "Say which framework the file refers to."})
        if upload.size > MAX_FILE_BYTES:
            raise ValidationError(
                {"file": f"File is larger than the {MAX_FILE_BYTES // (1024 * 1024)} MB limit."})
        refs = {}
        for c in self._controls_for(request):
            refs[matrix_lib.normalise_ref(c.control_id)] = c.pk
            refs[c.control_id.lower()] = c.pk
        try:
            result = matrix_lib.recognise(upload.name, upload.read(), vendor.name, refs)
        except ValueError as exc:
            raise ValidationError({"file": str(exc)})
        return Response(result)

    @action(detail=True, methods=["get"], url_path="matrix/export")
    def matrix_export(self, request, pk=None):
        """The matrix as CSV -- in our layout, or with ``?layout=vendor`` in the
        column layout of the file the vendor last sent, so it can go back to
        them looking like their own document with our side filled in."""
        from config.csvsafe import csv_safe

        vendor = self.get_object()
        data = self.matrix(request, pk=pk).data
        response = HttpResponse(content_type="text/csv")
        slug = "".join(ch if ch.isalnum() else "-" for ch in vendor.name).strip("-").lower()
        writer = csv.writer(response)
        if request.query_params.get("layout") == "vendor" and vendor.matrix_layout:
            response["Content-Disposition"] = (
                'attachment; filename="responsibility-matrix-' + slug + '-their-layout.csv"')
            rows = [r for r in data["rows"] if r["responsibility"]]
            header, lines = matrix_lib.render_layout(vendor.matrix_layout, rows)
            writer.writerow(header)
            for line in lines:
                writer.writerow(csv_safe(line))
            return response
        response["Content-Disposition"] = (
            'attachment; filename="responsibility-matrix-' + slug + '.csv"')
        writer.writerow(["Framework", "Control ID", "Title", "Responsibility",
                         "Provider statement", "Customer statement"])
        for r in data["rows"]:
            writer.writerow(csv_safe([
                r["framework"], r["control_id"], r["title"], r["responsibility"] or "",
                r["provider_statement"], r["customer_statement"],
            ]))
        return response

    @action(detail=False, methods=["get"])
    def questionnaire(self, request):
        """The shipped question set, so the UI never hard-codes it."""
        return Response(DEFAULT_QUESTIONNAIRE)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """The numbers the dashboard and the notifications feed share."""
        today = timezone.localdate()
        live = Vendor.objects.filter(status__in=("active", "offboarding"))
        rows = list(live.prefetch_related("assessments"))
        by_rating = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
        by_posture = {"none": 0, "unsatisfactory": 0, "expired": 0, "partial": 0, "current": 0}
        for v in rows:
            by_rating[v.risk_rating()] += 1
            by_posture[v.assurance()["posture"]] += 1
        expiring = VendorAssessment.objects.filter(
            vendor__in=live, expires_at__gte=today,
            expires_at__lte=today + timezone.timedelta(days=60),
        ).count()
        return Response({
            "vendors": len(rows),
            "by_rating": by_rating,
            "by_posture": by_posture,
            "reviews_overdue": sum(1 for v in rows if v.next_review_date and v.next_review_date < today),
            "assessments_expiring_60d": expiring,
        })

    @action(detail=False, methods=["get"])
    def export(self, request):
        from config.csvsafe import csv_safe

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="vendors.csv"'
        writer = csv.writer(response)
        writer.writerow(["Vendor", "Category", "Tier", "Status", "Data handled", "Owner",
                         "Assurance", "Current", "Expired", "Risk rating", "Next review",
                         "Controls", "Open risks"])
        for v in self.filter_queryset(self.get_queryset()):
            a = v.assurance()
            writer.writerow(csv_safe([
                v.name, v.category, v.get_tier_display(), v.get_status_display(), v.data_handled,
                v.owner.get_full_name() if v.owner else "", a["posture"], a["current"], a["expired"],
                v.risk_rating(), v.next_review_date or "",
                v.shared_responsibilities.values("control_id").distinct().count(),
                v.risks.filter(status__in=("open", "mitigating")).count(),
            ]))
        return response


class VendorAssessmentViewSet(viewsets.ModelViewSet):
    queryset = VendorAssessment.objects.select_related("vendor", "document", "reviewed_by")
    serializer_class = VendorAssessmentSerializer
    permission_classes = [CanManageFrameworks]
    filterset_fields = ["vendor", "kind", "result"]

    def get_serializer_context(self):
        from documents.access import accessible_folder_ids

        context = super().get_serializer_context()
        context["visible_folders"] = accessible_folder_ids(self.request.user)
        return context

    def perform_create(self, serializer):
        serializer.save(reviewed_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(reviewed_by=self.request.user)
