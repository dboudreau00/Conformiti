"""Document-management API: folders, permissions, documents, reviews, templates."""
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import CanManageDocuments
from .models import (
    Document,
    DocumentVersion,
    Folder,
    FolderPermission,
    FormTemplate,
)
from .access import accessible_folder_ids
from .permissions import DocumentAccessPermission, FolderAccessPermission
from .serializers import (
    DocumentSerializer,
    DocumentVersionSerializer,
    FolderPermissionSerializer,
    FolderSerializer,
    FormTemplateSerializer,
)


def _visible_folders(user):
    """Folders the user may at least view (permission inheritance resolved efficiently)."""
    ids = accessible_folder_ids(user)
    return list(
        Folder.objects.filter(id__in=ids).select_related("owner", "control", "parent")
    )


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer
    permission_classes = [FolderAccessPermission]
    filterset_fields = ["parent", "control", "is_framework_root"]
    search_fields = ["name"]

    def get_queryset(self):
        ids = accessible_folder_ids(self.request.user)
        return Folder.objects.filter(id__in=ids).select_related("owner", "control", "parent")

    def perform_create(self, serializer):
        user = self.request.user
        parent = serializer.validated_data.get("parent")
        allowed = user.can_manage_folders or (parent and parent.can_edit(user))
        if not allowed:
            raise PermissionDenied("You cannot create a folder here.")
        serializer.save()

    @action(detail=False, methods=["get"])
    def tree(self, request):
        """Return the folder hierarchy the user can see, as nested nodes."""
        folders = _visible_folders(request.user)
        by_parent = {}
        for f in folders:
            by_parent.setdefault(f.parent_id, []).append(f)

        def build(parent_id):
            nodes = []
            for f in sorted(by_parent.get(parent_id, []), key=lambda x: x.name):
                nodes.append({
                    "id": f.id, "name": f.name, "control": f.control_id,
                    "owner": f.owner.get_full_name() if f.owner else None,
                    "my_access": f.effective_access(request.user),
                    "document_count": f.documents.count(),
                    "children": build(f.id),
                })
            return nodes

        return Response(build(None))

    @action(detail=True, methods=["get"])
    def permissions(self, request, pk=None):
        folder = self.get_object()
        perms = FolderPermission.objects.filter(folder=folder).select_related("role", "user")
        return Response(FolderPermissionSerializer(perms, many=True).data)


class FolderPermissionViewSet(viewsets.ModelViewSet):
    serializer_class = FolderPermissionSerializer
    filterset_fields = ["folder", "role", "user"]

    def get_queryset(self):
        """Only expose grants on folders the caller can manage — the access-control
        map is itself sensitive, so it must not leak past folder permissions."""
        user = self.request.user
        qs = FolderPermission.objects.select_related("folder", "role", "user")
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
        self._check_manage(serializer.validated_data["folder"])
        serializer.save()

    def perform_update(self, serializer):
        # Guard both the existing folder and any folder the grant is being moved to.
        self._check_manage(serializer.instance.folder)
        target = serializer.validated_data.get("folder")
        if target is not None:
            self._check_manage(target)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_manage(instance.folder)
        instance.delete()


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [DocumentAccessPermission]
    filterset_fields = ["folder", "status", "owner", "control", "review_cadence"]
    search_fields = ["name", "description"]
    ordering_fields = ["updated_at", "next_review_date", "name"]

    def get_queryset(self):
        visible_ids = accessible_folder_ids(self.request.user)
        return (
            Document.objects.filter(folder_id__in=visible_ids)
            .select_related("folder", "owner", "control")
            .prefetch_related("control_links__control__category__framework")
        )

    def _require_folder_edit(self, folder):
        if not folder.can_edit(self.request.user):
            raise PermissionDenied("You need edit access to this folder.")

    def perform_create(self, serializer):
        folder = serializer.validated_data["folder"]
        self._require_folder_edit(folder)
        doc = serializer.save(
            created_by=self.request.user,
            owner=serializer.validated_data.get("owner") or self.request.user,
        )
        doc.compute_next_review()
        doc.save(update_fields=["next_review_date"])

    def perform_update(self, serializer):
        # Moving a document via PATCH must also require edit on the destination,
        # matching the dedicated `move` action (otherwise a doc could be planted
        # in a folder the user can't edit).
        new_folder = serializer.validated_data.get("folder")
        if new_folder is not None and new_folder.id != serializer.instance.folder_id:
            self._require_folder_edit(new_folder)
        doc = serializer.save()
        doc.compute_next_review()
        doc.save(update_fields=["next_review_date"])

    # --- actions -----------------------------------------------------------
    @action(detail=True, methods=["post"])
    def rename(self, request, pk=None):
        doc = self.get_object()
        self._require_folder_edit(doc.folder)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "A new name is required."})
        doc.name = name
        doc.save(update_fields=["name", "updated_at"])
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        doc = self.get_object()
        self._require_folder_edit(doc.folder)  # edit on source
        try:
            target = Folder.objects.get(pk=request.data.get("folder"))
        except Folder.DoesNotExist:
            raise ValidationError({"folder": "Target folder not found."})
        self._require_folder_edit(target)       # edit on destination
        doc.folder = target
        doc.save(update_fields=["folder", "updated_at"])
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def new_version(self, request, pk=None):
        """Archive the current file and attach a new one, bumping the version."""
        doc = self.get_object()
        self._require_folder_edit(doc.folder)
        new_file = request.data.get("file")
        if not new_file:
            raise ValidationError({"file": "A file is required."})
        if doc.file:
            DocumentVersion.objects.create(
                document=doc, version=doc.version, file=doc.file,
                note=request.data.get("note", ""), uploaded_by=request.user,
            )
        doc.file = new_file
        doc.version += 1
        doc.status = Document.Status.DRAFT
        doc.reminders_sent = []
        doc.save()
        return Response(DocumentSerializer(doc, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        doc = self.get_object()
        return Response(DocumentVersionSerializer(doc.versions.all(), many=True).data)

    @action(detail=True, methods=["post"])
    def mark_reviewed(self, request, pk=None):
        """Record a completed review: reset the review clock and clear reminders."""
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
        """Upcoming and overdue document reviews (drives the dashboard + calendar)."""
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
    """Central library of reusable blank forms/policy templates."""
    queryset = FormTemplate.objects.all()
    serializer_class = FormTemplateSerializer
    permission_classes = [CanManageDocuments]
    filterset_fields = ["category"]
    search_fields = ["name", "description"]
