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
from documents.serializers import person_name
from . import scoring
from .models import Control, ControlCategory, ControlEvidence, ControlMapping, Framework
from .serializers import (
    ControlEvidenceSerializer,
    ControlMappingSerializer,
    ControlSerializer,
    FrameworkSerializer,
)


# Spelled out because aggregate queries drop Meta.ordering; the id is a unique tie-break so pages never repeat or skip.
CONTROL_ORDER = ("category", "order", "control_id", "id")
MAX_BULK_DOCUMENTS = 500
# ControlDetail.jsx mirrors this number.
CHOICES_DOCUMENT_CAP = 500


def _controls_with_evidence_counts(user, qs=None):
    """Evidence counts cover only folders ``user`` can see, so the register never leaks documents past folder RBAC."""
    visible = accessible_folder_ids(user)
    base = qs if qs is not None else Control.objects.all()
    annotated = base.select_related(
        "category", "category__framework", "owner", "last_tested_by"
    ).annotate(
        evidence_count=Count(
            "evidence_links",
            filter=Q(evidence_links__document__folder_id__in=visible),
            distinct=True,
        )
    )
    return scoring.annotate(annotated, user).order_by(*CONTROL_ORDER)


class FrameworkViewSet(viewsets.ModelViewSet):
    queryset = Framework.objects.prefetch_related("categories").all()
    serializer_class = FrameworkSerializer
    permission_classes = [CanManageFrameworks]
    lookup_field = "key"

    @action(detail=True, methods=["get"])
    def controls(self, request, key=None):
        qs = _controls_with_evidence_counts(
            request.user, Control.objects.filter(category__framework__key=key)
        )
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return Response(ControlSerializer(qs, many=True, context={"request": request}).data)


class ControlViewSet(viewsets.ModelViewSet):
    queryset = Control.objects.select_related("category", "category__framework", "owner").all()
    serializer_class = ControlSerializer
    permission_classes = [CanManageFrameworks]
    # Seeded catalog: read and PATCH only. A create would 500 (no category) and DELETE would destroy catalog rows.
    http_method_names = ["get", "patch", "head", "options"]
    search_fields = ["control_id", "title", "objective"]
    filterset_fields = ["status", "owner", "category", "category__framework__key"]

    def get_queryset(self):
        return _controls_with_evidence_counts(self.request.user)

    @action(detail=True, methods=["get"])
    def readiness(self, request, pk=None):
        control = self.get_object()
        return Response({
            "control": control.pk,
            "control_id": control.control_id,
            **scoring.score_control(control, request.user),
        })

    @action(detail=False, methods=["get"])
    def export(self, request):
        """The register as CSV with the list's filters; ``q`` matches "<control_id> <title>" as the page shows it."""
        from django.db.models import Value
        from django.db.models.functions import Concat

        from config.csvsafe import csv_safe

        qs = self.filter_queryset(self.get_queryset())
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.annotate(_shown=Concat("control_id", Value(" "), "title")).filter(_shown__icontains=q)
        qs = qs.order_by(
            "category__framework__name", "category__order", "category__key", "order", "control_id"
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="controls.csv"'
        writer = csv.writer(response)
        writer.writerow(["Framework", "Version", "Category", "Control ID", "Title", "Status",
                         "Owner", "Evidence", "Readiness", "Band", "Last tested", "Objective"])
        for c in qs:
            readiness = scoring.score_control(c, request.user)
            writer.writerow(csv_safe([
                c.category.framework.name, c.category.framework.version, c.category.name,
                c.control_id, c.title, c.get_status_display(),
                person_name(c.owner), c.evidence_count,
                "" if readiness["score"] is None else readiness["score"],
                readiness["band_label"], c.last_tested_on or "", c.objective,
            ]))
        return response

    @action(detail=False, methods=["get"])
    def atlas(self, request):
        """Every control as one small record plus the crosswalk, keyed by id (``control_id`` is unique only within its
        category). ``score`` and ``band`` are the caller's, counting only the folders they can see."""
        categories = (
            ControlCategory.objects.select_related("framework")
            .order_by("framework__name", "framework__key", "framework_id", "order", "key", "id")
        )
        frameworks = {}
        for cat in categories:
            fw = cat.framework
            entry = frameworks.setdefault(fw.pk, {
                "id": fw.pk, "key": fw.key, "name": fw.name, "version": fw.version, "categories": [],
            })
            entry["categories"].append({"id": cat.pk, "key": cat.key, "name": cat.name})

        queryset = scoring.annotate(
            Control.objects.only(
                "id", "control_id", "title", "status", "owner", "last_tested_on",
                "test_interval_days", "category",
            ),
            request.user,
        ).order_by(*CONTROL_ORDER)
        controls = []
        for control in queryset:
            result = scoring.score_control(control)
            controls.append({
                "id": control.pk,
                "ref": control.control_id,
                "title": control.title,
                "category": control.category_id,
                "status": control.status,
                "score": result["score"],
                "band": result["band"],
            })

        # The auto-created join table is not workspace-scoped: members outside this workspace's controls are dropped.
        place = {c["id"]: i for i, c in enumerate(controls)}
        members, names = {}, {}
        rows = ControlMapping.objects.order_by("theme", "id").values_list("id", "theme", "controls")
        for mapping_id, theme, control_id in rows:
            if control_id in place:
                names[mapping_id] = theme
                members.setdefault(mapping_id, []).append(control_id)
        themes = [
            {"id": mapping_id, "theme": names[mapping_id], "controls": sorted(ids, key=place.__getitem__)}
            for mapping_id, ids in members.items()
            if len(ids) > 1
        ]
        return Response({"frameworks": list(frameworks.values()), "controls": controls, "themes": themes})


class ControlMappingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ControlMapping.objects.prefetch_related(
        "controls", "controls__category", "controls__category__framework"
    ).all()
    serializer_class = ControlMappingSerializer
    search_fields = ["theme"]


def _document_id(value):
    """A document id as an int; a numeric string is accepted so it matches the integer pks compared later."""
    number = None
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        try:
            number = int(value)
        except ValueError:
            pass
    # Past the database's integer type the query raises OverflowError, a 500 for what is only a wrong id.
    if number is None or abs(number) >= 2 ** 63:
        raise ValidationError({"documents": f"{value!r} is not a document id."})
    return number


class ControlEvidenceViewSet(viewsets.ModelViewSet):
    serializer_class = ControlEvidenceSerializer
    # Links are immutable audit artifacts: created and deleted, never edited.
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

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """Attach several documents to one control in a single call."""
        try:
            control = Control.objects.get(pk=request.data.get("control"))
        except (Control.DoesNotExist, TypeError, ValueError):
            raise ValidationError({"control": "Control not found."})
        raw_ids = request.data.get("documents")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValidationError({"documents": "Provide a non-empty list of document ids."})
        if len(raw_ids) > MAX_BULK_DOCUMENTS:
            raise ValidationError({"documents": f"At most {MAX_BULK_DOCUMENTS} documents per call."})
        doc_ids = []
        for value in raw_ids:
            number = _document_id(value)
            if number not in doc_ids:
                doc_ids.append(number)
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
        """Unpaginated pick-lists: visible documents (capped; ``documents_truncated`` says if more) and all controls."""
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
        ).order_by("category__framework__name", "category__order", "category__key", "order", "control_id")
        listed = list(docs[:CHOICES_DOCUMENT_CAP + 1])
        return Response({
            "documents": [
                {"id": d.id, "name": d.name, "path": d.folder.path, "status": d.status}
                for d in listed[:CHOICES_DOCUMENT_CAP]
            ],
            "documents_truncated": len(listed) > CHOICES_DOCUMENT_CAP,
            "controls": [
                {
                    "id": c.id, "label": c.control_id, "title": c.title,
                    "framework": c.category.framework.key,
                    "framework_name": c.category.framework.name,
                }
                for c in controls
            ],
        })
