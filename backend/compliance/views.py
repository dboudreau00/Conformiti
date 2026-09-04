"""Framework / control API views."""
import csv

from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import CanManageFrameworks
from documents.access import accessible_folder_ids
from documents.models import Document
from .models import Control, ControlEvidence, ControlMapping, Framework
from .serializers import (
    ControlEvidenceSerializer,
    ControlMappingSerializer,
    ControlSerializer,
    FrameworkSerializer,
)


def _controls_with_evidence_counts(user, qs=None):
    """Annotate controls with an evidence count restricted to the folders this
    user may see, so the mapping never leaks documents past folder RBAC."""
    visible = accessible_folder_ids(user)
    base = qs if qs is not None else Control.objects.all()
    return base.select_related("category", "category__framework", "owner").annotate(
        evidence_count=Count(
            "evidence_links",
            filter=Q(evidence_links__document__folder_id__in=visible),
            distinct=True,
        )
    )


class FrameworkViewSet(viewsets.ModelViewSet):
    queryset = Framework.objects.prefetch_related("categories").all()
    serializer_class = FrameworkSerializer
    permission_classes = [CanManageFrameworks]
    lookup_field = "key"

    @action(detail=True, methods=["get"])
    def controls(self, request, key=None):
        """All controls for a framework, grouped-ready and filterable by status."""
        qs = _controls_with_evidence_counts(
            request.user, Control.objects.filter(category__framework__key=key)
        )
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return Response(ControlSerializer(qs, many=True, context={"request": request}).data)


class ControlViewSet(viewsets.ModelViewSet):
    """List/retrieve controls; update status and owner (assign responsibility).

    Controls are seeded reference data: they're read and PATCHed (status/owner),
    never created or deleted through the API. Exposing create/PUT/DELETE would
    either 500 (control_id/title/category are read-only, so a create has no
    category) or let a manager destroy seeded catalog rows — so restrict the
    verbs to list/retrieve + PATCH."""
    queryset = Control.objects.select_related("category", "category__framework", "owner").all()
    serializer_class = ControlSerializer
    permission_classes = [CanManageFrameworks]
    http_method_names = ["get", "patch", "head", "options"]
    search_fields = ["control_id", "title", "objective"]
    filterset_fields = ["status", "owner", "category", "category__framework__key"]

    def get_queryset(self):
        return _controls_with_evidence_counts(self.request.user)

    @action(detail=False, methods=["get"])
    def export(self, request):
        """The control register as CSV (respects the same filters as the
        list: framework, status, owner, search). Evidence counts are the
        caller's visible counts, like the list."""
        from config.csvsafe import csv_safe

        qs = self.filter_queryset(self.get_queryset()).order_by(
            "category__framework__name", "category__order", "control_id"
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="controls.csv"'
        writer = csv.writer(response)
        writer.writerow(["Framework", "Version", "Category", "Control ID", "Title", "Status", "Owner", "Evidence", "Objective"])
        for c in qs:
            writer.writerow(csv_safe([
                c.category.framework.name, c.category.framework.version, c.category.name,
                c.control_id, c.title, c.get_status_display(),
                c.owner.get_full_name() if c.owner else "", c.evidence_count, c.objective,
            ]))
        return response


class ControlMappingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ControlMapping.objects.prefetch_related(
        "controls", "controls__category", "controls__category__framework"
    ).all()
    serializer_class = ControlMappingSerializer
    search_fields = ["theme"]


class ControlEvidenceViewSet(viewsets.ModelViewSet):
    """
    The control <-> evidence mapping. Links are immutable audit artifacts:
    they are created and deleted, never edited (so no PUT/PATCH).

    Visibility mirrors folder RBAC — you only see links whose document lives in
    a folder you can view. Creating or removing a link requires edit access to
    that document's folder, or the manage-frameworks capability.
    """
    serializer_class = ControlEvidenceSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ["control", "document", "control__category__framework__key"]

    def get_queryset(self):
        visible = accessible_folder_ids(self.request.user)
        return (
            ControlEvidence.objects.filter(document__folder_id__in=visible)
            .select_related(
                "document", "document__folder",
                "control", "control__category", "control__category__framework",
                "linked_by",
            )
        )

    # -- authorization helpers ----------------------------------------------
    def _can_link(self, document):
        user = self.request.user
        return user.can_manage_frameworks or document.folder.can_edit(user)

    def _deny(self):
        raise PermissionDenied(
            "You need edit access to that document's folder (or the frameworks "
            "capability) to change its evidence links."
        )

    def perform_create(self, serializer):
        document = serializer.validated_data["document"]
        if document.folder_id not in accessible_folder_ids(self.request.user):
            self._deny()  # can't link what you can't see
        if not self._can_link(document):
            self._deny()
        serializer.save(linked_by=self.request.user)

    def perform_destroy(self, instance):
        if not self._can_link(instance.document):
            self._deny()
        instance.delete()

    # -- actions --------------------------------------------------------------
    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """Attach several documents to one control in a single call — the
        audit-prep flow ('these five docs are the evidence for CC6.1')."""
        try:
            control = Control.objects.get(pk=request.data.get("control"))
        except (Control.DoesNotExist, TypeError, ValueError):
            raise ValidationError({"control": "Control not found."})
        doc_ids = request.data.get("documents")
        if not isinstance(doc_ids, list) or not doc_ids:
            raise ValidationError({"documents": "Provide a non-empty list of document ids."})
        note = str(request.data.get("note") or "")[:255]

        visible = accessible_folder_ids(request.user)
        documents = Document.objects.filter(
            pk__in=doc_ids, folder_id__in=visible
        ).select_related("folder")

        created, skipped = [], []
        for document in documents:
            if not self._can_link(document):
                skipped.append({"document": document.id, "reason": "no edit access"})
                continue
            link, was_created = ControlEvidence.objects.get_or_create(
                control=control, document=document,
                defaults={"note": note, "linked_by": request.user},
            )
            if was_created:
                created.append(link)
            else:
                skipped.append({"document": document.id, "reason": "already linked"})
        found_ids = {d.pk for d in documents}
        for missing in [i for i in doc_ids if i not in found_ids]:
            skipped.append({"document": missing, "reason": "not found or not visible"})

        return Response({
            "created": ControlEvidenceSerializer(created, many=True).data,
            "skipped": skipped,
        })

    @action(detail=False, methods=["get"])
    def choices(self, request):
        """Unpaginated pick-lists for the link UIs: the caller's visible
        documents and the full control catalog (small: ~217 rows)."""
        visible = accessible_folder_ids(request.user)
        q = (request.query_params.get("q") or "").strip()
        docs = (
            Document.objects.filter(folder_id__in=visible)
            .select_related("folder").order_by("name")
        )
        if q:
            docs = docs.filter(name__icontains=q)
        controls = Control.objects.select_related(
            "category", "category__framework"
        ).order_by("category__framework__name", "category__order", "control_id")
        return Response({
            "documents": [
                {"id": d.id, "name": d.name, "path": d.folder.path, "status": d.status}
                for d in docs[:500]
            ],
            "controls": [
                {
                    "id": c.id, "label": c.control_id, "title": c.title,
                    "framework": c.category.framework.key,
                    "framework_name": c.category.framework.name,
                }
                for c in controls
            ],
        })
