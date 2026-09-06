"""Serializers for frameworks and controls."""
from django.utils import timezone
from rest_framework import serializers

from . import scoring
from accounts.tenancy import CurrentWorkspaceDefault

from .models import Control, ControlCategory, ControlEvidence, ControlMapping, Framework


class ControlSerializer(serializers.ModelSerializer):
    framework = serializers.CharField(source="category.framework.name", read_only=True)
    framework_key = serializers.CharField(source="category.framework.key", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    evidence_count = serializers.SerializerMethodField()
    readiness_score = serializers.SerializerMethodField()
    readiness_band = serializers.SerializerMethodField()
    readiness_band_label = serializers.SerializerMethodField()
    last_tested_by_name = serializers.CharField(
        source="last_tested_by.get_full_name", read_only=True, default="")

    class Meta:
        model = Control
        fields = [
            "id", "control_id", "title", "objective", "status", "owner",
            "owner_name", "category", "category_name", "framework", "framework_key",
            "evidence_count", "last_tested_on", "test_interval_days",
            "last_tested_by_name", "last_tested_recorded_at",
            "readiness_score", "readiness_band", "readiness_band_label",
        ]
        read_only_fields = ["control_id", "title", "objective", "category",
                            "last_tested_by_name", "last_tested_recorded_at"]

    def _readiness(self, obj):
        """Memoised: three fields would otherwise score the same row three times."""
        cached = getattr(obj, "_readiness_cache", None)
        if cached is None:
            request = self.context.get("request")
            cached = scoring.score_control(obj, request.user if request else None)
            obj._readiness_cache = cached
        return cached

    def get_readiness_score(self, obj):
        return self._readiness(obj)["score"]

    def get_readiness_band(self, obj):
        return self._readiness(obj)["band"]

    def get_readiness_band_label(self, obj):
        return self._readiness(obj)["band_label"]

    def validate_last_tested_on(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError("A test date cannot be in the future.")
        return value

    def validate_test_interval_days(self, value):
        if value is not None and not (1 <= value <= 3650):
            raise serializers.ValidationError("Choose an interval between 1 and 3650 days.")
        return value

    def update(self, instance, validated_data):
        """Stamp who recorded a test and when, and audit it explicitly.

        audit.middleware records field NAMES only, so without this a backdated
        test date is indistinguishable from any other edit."""
        recording = ("last_tested_on" in validated_data
                     and validated_data["last_tested_on"] != instance.last_tested_on)
        previous = instance.last_tested_on
        if recording:
            request = self.context.get("request")
            validated_data["last_tested_by"] = getattr(request, "user", None)
            validated_data["last_tested_recorded_at"] = timezone.now()
        control = super().update(instance, validated_data)
        if recording:
            self._audit_test(control, previous)
        return control

    def _audit_test(self, control, previous):
        from audit.models import AuditLog
        from audit.middleware import _client_ip

        request = self.context.get("request")
        if request is None:
            return
        try:
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="update", object_type="controls", object_id=str(control.pk),
                detail=f"{control.control_id} last_tested_on {previous or 'never'} "
                       f"-> {control.last_tested_on}"[:255],
                ip_address=_client_ip(request),
            )
        except Exception:  # pragma: no cover - logging must not block the write
            pass

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


class ControlRefSerializer(serializers.ModelSerializer):
    """A control reference without the scored fields.

    The crosswalk nests controls many-deep over every mapping; scoring there
    would run three unannotated signal queries per row for a screen that does
    not show a score.
    """
    framework_key = serializers.CharField(source="category.framework.key", read_only=True)
    framework = serializers.CharField(source="category.framework.name", read_only=True)

    class Meta:
        model = Control
        fields = ["id", "control_id", "title", "status", "framework", "framework_key"]


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
    workspace = serializers.HiddenField(default=CurrentWorkspaceDefault())

    class Meta:
        model = Framework
        fields = [
            "id", "key", "name", "version", "authority", "description",
            "categories", "control_count", "implemented_count", "workspace",
        ]

    def get_control_count(self, obj):
        return Control.objects.filter(category__framework=obj).count()

    def get_implemented_count(self, obj):
        return Control.objects.filter(
            category__framework=obj, status=Control.Status.IMPLEMENTED
        ).count()


class ControlMappingSerializer(serializers.ModelSerializer):
    # ControlRefSerializer, not ControlSerializer: the crosswalk nests controls
    # across every mapping and does not show a readiness score, so scoring here
    # would cost three unannotated queries per row for nothing.
    controls = ControlRefSerializer(many=True, read_only=True)

    class Meta:
        model = ControlMapping
        fields = ["id", "theme", "controls"]
