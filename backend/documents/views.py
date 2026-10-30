import re

import django_filters as filters
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ErrorDetail, PermissionDenied, ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import CanManageDocuments
from audit.events import record_evidence_read
from .models import (
    Document,
    DocumentVersion,
    Folder,
    FolderPermission,
    FormTemplate,
)
from config.personfilters import person

from .access import accessible_folder_ids
from . import monitor
from .downloads import download_filename, serve_inline, serve_stored_file
from . import preview as preview_lib
from .scanning import scan_or_raise
from .permissions import DocumentAccessPermission, FolderAccessPermission
from .serializers import (
    DocumentSerializer,
    DocumentVersionSerializer,
    FolderPermissionSerializer,
    FolderSerializer,
    FormTemplateSerializer,
    person_name,
)
from .uploads import validate_upload


def _natural_key(name):
    """Sort key that reads digit runs as numbers ("A.5.2" before "A.5.10"). Text is at even positions, numbers at odd,
    so two keys never compare a number with a string; the name breaks ties."""
    parts = re.split(r"(\d+)", name or "")
    return [int(p) if i % 2 else p.casefold() for i, p in enumerate(parts)], name or ""


def _visible_folders(user):
    ids = accessible_folder_ids(user)
    return list(
        Folder.objects.filter(id__in=ids).select_related("owner", "control", "parent")
    )


def _missing_pk(pk):
    """DRF's wording for a missing primary key, so a hidden row and a missing id get the same answer."""
    return [ErrorDetail(f'Invalid pk "{pk}" - object does not exist.', code="does_not_exist")]


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer
    permission_classes = [IsAuthenticated, FolderAccessPermission]
    filterset_fields = ["parent", "control", "is_framework_root"]
    search_fields = ["name"]

    def get_queryset(self):
        ids = accessible_folder_ids(self.request.user)
        return Folder.objects.filter(id__in=ids).select_related("owner", "control", "parent")

    def list(self, request, *args, **kwargs):
        """Folders in clause order, top level first, unless the caller sends ``ordering``; SQL sorts names as text."""
        queryset = self.filter_queryset(self.get_queryset())
        if OrderingFilter().get_ordering(request, queryset, self) is None:
            queryset = sorted(queryset, key=lambda f: (
                f.parent_id is not None, f.parent_id or 0, _natural_key(f.name)))
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    def perform_create(self, serializer):
        user = self.request.user
        parent = serializer.validated_data.get("parent")
        # A parent the caller cannot see is answered as missing: a 403 would confirm a hidden folder.
        if parent is not None and not parent.can_view(user):
            raise ValidationError({"parent": _missing_pk(parent.pk)})
        allowed = user.can_manage_folders or (parent and parent.can_edit(user))
        if not allowed:
            raise PermissionDenied("You cannot create a folder here.")
        serializer.save()

    def perform_update(self, serializer):
        """A move exposes the subtree to the destination's grants: manage on the folder, edit on the destination."""
        folder = serializer.instance
        user = self.request.user
        new_parent = serializer.validated_data.get("parent", folder.parent)
        if (new_parent.id if new_parent else None) != folder.parent_id:
            if new_parent is not None and not new_parent.can_view(user):
                raise ValidationError({"parent": _missing_pk(new_parent.pk)})
            if folder.is_seeded:
                raise PermissionDenied("Framework folders are generated from the control library and cannot be moved.")
            if not folder.can_manage(user):
                raise PermissionDenied("You need manage access on a folder to move it.")
            if new_parent is not None and not new_parent.can_edit(user):
                raise PermissionDenied("You need edit access on the destination folder.")
            if new_parent is None and not user.can_manage_folders:
                raise PermissionDenied("Only folder managers can create top-level folders.")
        if "name" in serializer.validated_data and folder.is_seeded \
                and serializer.validated_data["name"] != folder.name:
            raise PermissionDenied("Framework folders are named from the control library and cannot be renamed.")
        # The owner counts as a manager, so taking ownership with only edit access would be a self-service promotion.
        new_owner = serializer.validated_data.get("owner", folder.owner)
        if (new_owner.id if new_owner else None) != folder.owner_id and not folder.can_manage(user):
            raise PermissionDenied("You need manage access on a folder to change its owner.")
        serializer.save()

    def perform_destroy(self, instance):
        # Deleting a generated framework/category/control folder would cascade every document and grant beneath it.
        if instance.is_seeded:
            raise PermissionDenied("Framework folders cannot be deleted.")
        instance.delete()

    @action(detail=False, methods=["get"])
    def tree(self, request):
        folders = _visible_folders(request.user)
        # A folder whose parent is not visible is a root of this user's view: bucketing strictly by parent_id would
        # orphan a mid-tree grant and render an empty tree.
        visible_ids = {f.id for f in folders}
        by_parent = {}
        for f in folders:
            key = f.parent_id if f.parent_id in visible_ids else None
            by_parent.setdefault(key, []).append(f)

        from django.db.models import Count

        from .access import bulk_effective_access

        access = bulk_effective_access(request.user, folders)
        counts = dict(
            Document.objects.filter(folder_id__in=visible_ids)
            .values_list("folder_id").annotate(n=Count("id")).values_list("folder_id", "n"))

        def build(parent_id):
            nodes = []
            for f in sorted(by_parent.get(parent_id, []), key=lambda x: _natural_key(x.name)):
                nodes.append({
                    "id": f.id, "name": f.name, "control": f.control_id,
                    "owner": person_name(f.owner) or None,
                    "my_access": access.get(f.id),
                    "is_seeded": f.is_seeded,
                    "document_count": counts.get(f.id, 0),
                    "children": build(f.id),
                })
            return nodes

        return Response(build(None))

    @action(detail=True, methods=["get"])
    def permissions(self, request, pk=None):
        """Who can reach this folder. The map is as sensitive as the folder, so it takes manage, as
        FolderPermissionViewSet does."""
        folder = self.get_object()
        user = request.user
        if not (user.can_manage_folders or user.can_view_all or user.is_superuser
                or folder.can_manage(user)):
            raise PermissionDenied("You need manage access on a folder to see who can reach it.")
        perms = FolderPermission.objects.filter(folder=folder).select_related("role", "user")
        return Response(FolderPermissionSerializer(perms, many=True).data)


class FolderPermissionViewSet(viewsets.ModelViewSet):
    serializer_class = FolderPermissionSerializer
    filterset_fields = ["folder", "role", "user"]

    def get_queryset(self):
        """Grants on folders the caller can manage: the access-control map must not leak past folder permissions."""
        user = self.request.user
        # No Meta.ordering on the model: order_by("id") keeps a paged list from repeating or dropping a grant.
        qs = FolderPermission.objects.select_related("folder", "role", "user").order_by("id")
        if user.can_manage_folders or user.can_view_all or user.is_superuser:
            return qs
        manageable = [
            f.id for f in Folder.objects.select_related("parent", "owner")
            if f.can_manage(user)
        ]
        return qs.filter(folder_id__in=manageable)

    def _check_manage(self, folder):
        if not folder.can_manage(self.request.user):
            raise PermissionDenied("You must be able to manage this folder to change its access.")

    def perform_create(self, serializer):
        folder = serializer.validated_data["folder"]
        # View first, then manage: a folder they cannot see must not be confirmed by a 403.
        if not folder.can_view(self.request.user):
            raise ValidationError({"folder": _missing_pk(folder.pk)})
        self._check_manage(folder)
        serializer.save()

    def perform_update(self, serializer):
        self._check_manage(serializer.instance.folder)
        target = serializer.validated_data.get("folder")
        if target is not None:
            if not target.can_view(self.request.user):
                raise ValidationError({"folder": _missing_pk(target.pk)})
            self._check_manage(target)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_manage(instance.folder)
        instance.delete()


class DocumentFilter(filters.FilterSet):
    """``owner`` filters as a plain number: a ModelChoiceFilter would tell an auditor whether an id is a person."""

    owner = person("owner_id")

    class Meta:
        model = Document
        fields = ["folder", "status", "owner", "control", "review_cadence"]


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated, DocumentAccessPermission]
    filterset_class = DocumentFilter
    search_fields = ["name", "description"]
    ordering_fields = ["updated_at", "next_review_date", "name"]

    def get_queryset(self):
        from django.db.models import Prefetch

        from compliance.models import ControlEvidence

        visible_ids = accessible_folder_ids(self.request.user)
        # select_related, not nested prefetches: on SQLite a forward-key prefetch becomes one OR clause per related row,
        # and a policy mapped into every library carries thousands of links, past SQLite's expression depth of 1000.
        links = ControlEvidence.objects.select_related("control__category__framework")
        return (
            Document.objects.filter(folder_id__in=visible_ids)
            .select_related("folder", "owner", "control")
            .prefetch_related(Prefetch("control_links", queryset=links))
        )

    def _require_folder_edit(self, folder):
        if not folder.can_edit(self.request.user):
            raise PermissionDenied("You need edit access to this folder.")

    def _require_target_folder(self, folder):
        """A destination folder the caller cannot see is answered as missing; one they can see but not edit is a 403."""
        if not folder.can_view(self.request.user):
            raise ValidationError({"folder": _missing_pk(folder.pk)})
        self._require_folder_edit(folder)

    def perform_create(self, serializer):
        folder = serializer.validated_data["folder"]
        self._require_target_folder(folder)
        # After the permission check, not in validate_file: an unauthorised caller must not reach the scanner.
        scan_or_raise(serializer.validated_data.get("file"), self.request)
        doc = serializer.save(
            created_by=self.request.user,
            owner=serializer.validated_data.get("owner") or self.request.user,
        )
        doc.compute_next_review()
        doc.save(update_fields=["next_review_date"])
        monitor.mark_clean(doc)

    def perform_update(self, serializer):
        # A PATCH of the file would skip new_version's scan, archive and version bump, and keep a stale scan verdict.
        if "file" in serializer.validated_data:
            raise ValidationError(
                {"file": "Upload a new version instead: POST /documents/{id}/new_version/."})
        # Moving by PATCH needs what `move` needs: edit on the destination (else a document could be planted there)
        # and on the source, since an owner with view alone must not take evidence out of a folder.
        new_folder = serializer.validated_data.get("folder")
        if new_folder is not None and new_folder.id != serializer.instance.folder_id:
            # Destination first: checking the source first answered 403 for a hidden folder and 400 for a missing one.
            self._require_target_folder(new_folder)
            self._require_folder_edit(serializer.instance.folder)
        before = serializer.instance.next_review_date
        doc = serializer.save()
        doc.compute_next_review()
        fields = ["next_review_date"]
        # A changed review date needs fresh reminder windows, or the overdue sentinel silences every later reminder.
        if doc.next_review_date != before:
            doc.reminders_sent = []
            fields.append("reminders_sent")
        doc.save(update_fields=fields)

    @action(detail=True, methods=["post"])
    def rename(self, request, pk=None):
        doc = self.get_object()
        self._require_folder_edit(doc.folder)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "A new name is required."})
        doc.name = name[:255]
        doc.save(update_fields=["name", "updated_at"])
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        doc = self.get_object()
        self._require_folder_edit(doc.folder)
        raw = request.data.get("folder")
        # True is 1 and 1.5 truncates to 1: either would move the document into a folder the caller never named.
        if isinstance(raw, (bool, float)):
            raise ValidationError({"folder": "Target folder not found."})
        try:
            target = Folder.objects.get(pk=raw)
        except (Folder.DoesNotExist, TypeError, ValueError):
            raise ValidationError({"folder": "Target folder not found."})
        # A hidden folder is "not found" too: a 403 would confirm it exists.
        if not target.can_view(request.user):
            raise ValidationError({"folder": "Target folder not found."})
        self._require_folder_edit(target)
        doc.folder = target
        doc.save(update_fields=["folder", "updated_at"])
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def new_version(self, request, pk=None):
        doc = self.get_object()
        self._require_folder_edit(doc.folder)
        new_file = request.FILES.get("file") or request.data.get("file")
        if not new_file or isinstance(new_file, str):
            raise ValidationError({"file": "A file is required."})
        try:
            validate_upload(new_file)
        except ValidationError as exc:
            raise ValidationError({"file": exc.detail})
        scan_or_raise(new_file, request)
        # Never archive quarantined bytes: archived versions are a download route of their own and are not re-scanned.
        if doc.file and not doc.quarantined_at:
            DocumentVersion.objects.create(
                document=doc, version=doc.version, file=doc.file,
                note=str(request.data.get("note", ""))[:255], uploaded_by=request.user,
            )
        doc.file = new_file
        doc.version += 1
        doc.status = Document.Status.DRAFT
        doc.reminders_sent = []
        # A new file is a new scan subject: the old version's quarantine and verdict are cleared.
        doc.quarantined_at = None
        doc.scan_status = Document.Scan.UNSCANNED
        doc.scan_signature = ""
        doc.save()
        monitor.mark_clean(doc)
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        doc = monitor.refuse_if_quarantined(self.get_object())
        record_evidence_read(request, doc)
        return serve_stored_file(doc.file, doc.name)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """PDFs and images stream inline after a magic-byte check; Word, Excel and text come back as structured JSON."""
        doc = monitor.refuse_if_quarantined(self.get_object())
        return preview_response(request, doc.file, doc.name, doc)

    @action(detail=True, methods=["get"], url_path=r"versions/(?P<version_pk>[^/.]+)/download")
    def download_version(self, request, pk=None, version_pk=None):
        doc = monitor.refuse_if_quarantined(self.get_object())
        try:
            version = doc.versions.get(pk=version_pk)
        except (DocumentVersion.DoesNotExist, ValueError):
            # ValueError: the URL pattern accepts any text, so a non-numeric id reaches the query.
            raise ValidationError({"version": "Not found."})
        record_evidence_read(request, doc, version=version.version)
        # The tag goes before the archived file's own extension, which need not be the current file's.
        return serve_stored_file(
            version.file, download_filename(doc.name, version.file.name, f" (v{version.version})"))

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        doc = self.get_object()
        return Response(DocumentVersionSerializer(doc.versions.all(), many=True).data)

    @action(detail=True, methods=["post"])
    def mark_reviewed(self, request, pk=None):
        doc = self.get_object()
        self._require_folder_edit(doc.folder)
        doc.last_reviewed = timezone.now().date()
        doc.status = Document.Status.APPROVED
        doc.reminders_sent = []
        doc.compute_next_review()
        doc.save()
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def reviews(self, request):
        try:
            horizon = int(request.query_params.get("days", 90))
        except (TypeError, ValueError):
            horizon = 90
        horizon = max(0, min(horizon, 3650))
        today = timezone.now().date()
        docs = [d for d in self.get_queryset().exclude(next_review_date=None)
                if d.next_review_date is not None
                and (d.next_review_date - today).days <= horizon]
        docs.sort(key=lambda d: d.next_review_date)
        return Response(DocumentSerializer(docs, many=True, context={"request": request}).data)


class FormTemplateViewSet(viewsets.ModelViewSet):
    queryset = FormTemplate.objects.all()
    serializer_class = FormTemplateSerializer
    permission_classes = [CanManageDocuments]
    filterset_fields = ["category"]
    search_fields = ["name", "description"]

    # Blank templates are internal: an external auditor reads only the package they were issued.
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.none() if self.request.user.is_auditor else qs

    def perform_create(self, serializer):
        scan_or_raise(serializer.validated_data.get("file"), self.request)
        serializer.save()

    def perform_update(self, serializer):
        scan_or_raise(serializer.validated_data.get("file"), self.request)
        serializer.save()

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Not audited (templates are not evidence), but served through the API so no storage path is published."""
        return serve_stored_file(self.get_object().file, self.get_object().name)


def preview_response(request, file_field, name, document, version=None):
    """Shared by the document and package-evidence preview endpoints."""
    if not file_field:
        raise ValidationError({"detail": "This document has no file."})
    try:
        result = preview_lib.render(file_field, name)
    except preview_lib.PreviewError as exc:
        return Response({"kind": None, "detail": str(exc)}, status=415)
    record_evidence_read(request, document, version=version)
    if result["kind"] == "pdf":
        return serve_inline(file_field, "application/pdf", name)
    if result["kind"] == "image":
        with file_field.open("rb") as fh:
            head = fh.read(16)
        return serve_inline(file_field, preview_lib.image_content_type(head), name)
    return Response(result)
