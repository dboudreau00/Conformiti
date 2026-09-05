from django.utils import timezone
from rest_framework import serializers

from .models import (
    DEFAULT_QUESTIONNAIRE, QuestionnaireInvite, SharedResponsibility, Vendor, VendorAssessment,
)
from .questionnaire import validate_answers


class QuestionnaireInviteSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    assessment_result = serializers.CharField(source="assessment.result", read_only=True, default=None)

    class Meta:
        model = QuestionnaireInvite
        # token_hash is deliberately absent; the link itself is returned once,
        # by the send action, and never again.
        fields = [
            "id", "vendor", "vendor_name", "sent_to", "message", "sent_by_name", "sent_at",
            "email_sent", "expires_at", "opened_at", "saved_at", "submitted_at",
            "respondent_name", "respondent_title", "assessment", "assessment_result",
            "revoked_at", "status",
        ]
        read_only_fields = fields


class VendorAssessmentSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    result_display = serializers.CharField(source="get_result_display", read_only=True)
    document_name = serializers.CharField(source="document.name", read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source="reviewed_by.get_full_name", read_only=True, default="")
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = VendorAssessment
        fields = [
            "id", "vendor", "kind", "kind_display", "title", "period_start", "period_end",
            "issued_at", "expires_at", "result", "result_display", "document", "document_name",
            "answers", "findings", "reviewed_by", "reviewed_by_name", "is_expired",
            "created_at", "updated_at",
        ]
        read_only_fields = ["reviewed_by"]

    def validate(self, attrs):
        start, end = attrs.get("period_start"), attrs.get("period_end")
        if start and end and end < start:
            raise serializers.ValidationError({"period_end": "The period cannot end before it starts."})
        issued, expires = attrs.get("issued_at"), attrs.get("expires_at")
        if issued and expires and expires < issued:
            raise serializers.ValidationError({"expires_at": "Cannot expire before it was issued."})
        return attrs

    def validate_answers(self, value):
        """Answers are keyed by the shipped question ids; anything else is a
        client bug rather than data."""
        try:
            return validate_answers(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

    def validate_document(self, doc):
        """A report pinned to a vendor must be one the caller can see, or the
        assessment becomes a way to name documents behind folder permissions."""
        if doc is None:
            return doc
        if doc.folder_id not in self._visible_folders():
            raise serializers.ValidationError("You cannot see that document.")
        return doc

    def _visible_folders(self):
        visible = self.context.get("visible_folders")
        if visible is None:
            from documents.access import accessible_folder_ids
            request = self.context.get("request")
            visible = accessible_folder_ids(request.user) if request is not None else set()
            self.context["visible_folders"] = visible
        return visible

    def to_representation(self, instance):
        """The same rule on the way out: a reader who cannot open the folder
        learns that a copy is filed, not which document it is."""
        data = super().to_representation(instance)
        hidden = bool(instance.document_id) and instance.document.folder_id not in self._visible_folders()
        if hidden:
            data["document"] = None
            data["document_name"] = None
        data["document_hidden"] = hidden
        return data


class VendorSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    tier_display = serializers.CharField(source="get_tier_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    assurance = serializers.SerializerMethodField()
    risk_rating = serializers.SerializerMethodField()
    assessment_count = serializers.SerializerMethodField()
    control_count = serializers.SerializerMethodField()
    open_risk_count = serializers.SerializerMethodField()
    is_review_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id", "name", "category", "website", "contact_name", "contact_email",
            "tier", "tier_display", "status", "status_display", "data_handled", "services",
            "owner", "owner_name", "review_cadence", "last_reviewed", "next_review_date",
            "is_review_overdue", "notes", "assurance", "risk_rating", "assessment_count",
            "control_count", "open_risk_count", "matrix_layout", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "next_review_date", "matrix_layout"]

    def get_assurance(self, obj):
        return obj.assurance()

    def get_risk_rating(self, obj):
        return obj.risk_rating()

    # The view annotates these; the fallbacks keep the serializer honest when
    # it is handed a bare instance (a management command, a test).
    def get_assessment_count(self, obj):
        n = getattr(obj, "n_assessments", None)
        return n if n is not None else obj.assessments.count()

    def get_control_count(self, obj):
        n = getattr(obj, "n_controls", None)
        return n if n is not None else obj.shared_responsibilities.values("control_id").distinct().count()

    def get_open_risk_count(self, obj):
        n = getattr(obj, "n_open_risks", None)
        return n if n is not None else obj.risks.filter(status__in=("open", "mitigating")).count()

    def get_is_review_overdue(self, obj):
        return bool(obj.next_review_date and obj.next_review_date < timezone.localdate())

    def validate_website(self, value):
        if value and not value.lower().startswith("https://"):
            raise serializers.ValidationError("Use an https:// address.")
        return value


class VendorDetailSerializer(VendorSerializer):
    assessments = VendorAssessmentSerializer(many=True, read_only=True)
    questionnaire = serializers.SerializerMethodField()
    questionnaire_invites = serializers.SerializerMethodField()

    class Meta(VendorSerializer.Meta):
        fields = VendorSerializer.Meta.fields + ["assessments", "questionnaire", "questionnaire_invites"]

    def get_questionnaire(self, obj):
        return DEFAULT_QUESTIONNAIRE

    def get_questionnaire_invites(self, obj):
        rows = obj.questionnaire_invites.select_related("sent_by", "assessment")[:10]
        return QuestionnaireInviteSerializer(rows, many=True).data


class SharedResponsibilitySerializer(serializers.ModelSerializer):
    control_label = serializers.CharField(source="control.control_id", read_only=True)
    control_title = serializers.CharField(source="control.title", read_only=True)
    responsibility_display = serializers.CharField(source="get_responsibility_display", read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.get_full_name", read_only=True, default="")

    class Meta:
        model = SharedResponsibility
        fields = [
            "id", "vendor", "control", "control_label", "control_title",
            "responsibility", "responsibility_display",
            "provider_statement", "customer_statement", "source",
            "updated_by_name", "updated_at",
        ]
        read_only_fields = ["source"]
