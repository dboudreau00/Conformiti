"""Serializers for frameworks and controls."""
from rest_framework import serializers

from .models import Control, ControlCategory, ControlEvidence, ControlMapping, Framework


class ControlSerializer(serializers.ModelSerializer):
    framework = serializers.CharField(source="category.framework.name", read_only=True)
    framework_key = serializers.CharField(source="category.framework.key", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    evidence_count = serializers.SerializerMethodField()

    class Meta:
        model = Control
        fields = [
            "id", "control_id", "title", "objective", "status", "owner",
            "owner_name", "category", "category_name", "framework", "framework_key",
            "evidence_count",
        ]
        read_only_fields = ["control_id", "title", "objective", "category"]

    def get_evidence_count(self, obj):
        """Prefer the view's visibility-filtered annotation; otherwise compute a
        count restricted to folders the requester can see, so the number never
        reveals evidence hidden behind folder permissions."""
        annotated = getattr(obj, "evidence_count", None)
        if annotated is not None:
            return annotated
        request = self.context.get("request")
        qs = obj.evidence_links.all()
        if request is not None:
            from documents.access import accessible_folder_ids
            qs = qs.filter(document__folder_id__in=accessible_folder_ids(request.user))
        return qs.count()


class ControlEvidenceSerializer(serializers.ModelSerializer):
    # Document side (for the control detail panel)
    document_name = serializers.CharField(source="document.name", read_only=True)
    document_status = serializers.CharField(source="document.status", read_only=True)
    folder_path = serializers.CharField(source="document.folder.path", read_only=True)
    # Control side (for the document "satisfies" panel)
    control_label = serializers.CharField(source="control.control_id", read_only=True)
    control_title = serializers.CharField(source="control.title", read_only=True)
    framework_key = serializers.CharField(source="control.category.framework.key", read_only=True)
    framework_name = serializers.CharField(source="control.category.framework.name", read_only=True)
    linked_by_name = serializers.CharField(source="linked_by.get_full_name", read_only=True, default="")
    # Whether the *requesting* user may remove this link — the UI uses it to
    # show the Unlink control only where the API would accept the call.
    can_unlink = serializers.SerializerMethodField()

    class Meta:
        model = ControlEvidence
        fields = [
            "id", "control", "document", "note", "created_at",
            "document_name", "document_status", "folder_path",
            "control_label", "control_title", "framework_key", "framework_name",
            "linked_by_name", "can_unlink",
        ]
        read_only_fields = ["created_at"]

    def get_can_unlink(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        user = request.user
        return bool(user.can_manage_frameworks or obj.document.folder.can_edit(user))


class ControlCategorySerializer(serializers.ModelSerializer):
    control_count = serializers.IntegerField(source="controls.count", read_only=True)

    class Meta:
        model = ControlCategory
        fields = ["id", "key", "name", "order", "control_count"]


class FrameworkSerializer(serializers.ModelSerializer):
    categories = ControlCategorySerializer(many=True, read_only=True)
    control_count = serializers.SerializerMethodField()
    implemented_count = serializers.SerializerMethodField()

    class Meta:
        model = Framework
        fields = [
            "id", "key", "name", "version", "authority", "description",
            "categories", "control_count", "implemented_count",
        ]

    def get_control_count(self, obj):
        return Control.objects.filter(category__framework=obj).count()

    def get_implemented_count(self, obj):
        return Control.objects.filter(
            category__framework=obj, status=Control.Status.IMPLEMENTED
        ).count()


class ControlMappingSerializer(serializers.ModelSerializer):
    controls = ControlSerializer(many=True, read_only=True)

    class Meta:
        model = ControlMapping
        fields = ["id", "theme", "controls"]
