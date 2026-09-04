"""Serializers for access reviews, meeting cadence, and champion groups."""
import math

from django.utils import timezone
from rest_framework import serializers

from .models import (
    AccessReview,
    AccessReviewItem,
    ChampionGroup,
    GroupMember,
    MeetingMinute,
    MeetingSeries,
)


# --------------------------------------------------------------------------- #
# Access reviews
# --------------------------------------------------------------------------- #
class AccessReviewItemSerializer(serializers.ModelSerializer):
    decided_by_name = serializers.CharField(source="decided_by.get_full_name", read_only=True, default="")

    class Meta:
        model = AccessReviewItem
        fields = [
            "id", "review", "user", "username", "full_name", "email", "job_title",
            "role_name", "is_active", "last_login", "folder_grants", "capabilities",
            "decision", "decision_notes", "decided_by", "decided_by_name", "decided_at",
        ]
        read_only_fields = [
            "review", "user", "username", "full_name", "email", "job_title",
            "role_name", "is_active", "last_login", "folder_grants", "capabilities",
            "decided_by", "decided_at",
        ]

    def validate(self, attrs):
        if self.instance and self.instance.review.status == AccessReview.Status.COMPLETED:
            raise serializers.ValidationError("This review is completed and read-only.")
        return attrs

    def update(self, instance, validated_data):
        request = self.context.get("request")
        new_decision = validated_data.get("decision", instance.decision)
        if new_decision != instance.decision:
            if new_decision == AccessReviewItem.Decision.PENDING:
                validated_data["decided_by"] = None
                validated_data["decided_at"] = None
            else:
                validated_data["decided_by"] = request.user if request else None
                validated_data["decided_at"] = timezone.now()
        return super().update(instance, validated_data)


class AccessReviewSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True, default="")
    item_count = serializers.SerializerMethodField()
    decided_count = serializers.SerializerMethodField()

    class Meta:
        model = AccessReview
        fields = [
            "id", "name", "status", "notes", "created_by", "created_by_name",
            "created_at", "completed_at", "item_count", "decided_count",
        ]
        read_only_fields = ["status", "created_by", "completed_at"]

    def get_item_count(self, obj):
        return obj.items.count()

    def get_decided_count(self, obj):
        return obj.items.exclude(decision=AccessReviewItem.Decision.PENDING).count()


# --------------------------------------------------------------------------- #
# Meeting cadence
# --------------------------------------------------------------------------- #
class MeetingMinuteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True, default="")

    def validate_file(self, value):
        from documents.uploads import validate_upload
        return validate_upload(value)

    class Meta:
        model = MeetingMinute
        fields = [
            "id", "series", "date", "title", "attendees", "notes", "file",
            "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = ["created_by"]


class MeetingSeriesSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    held_this_year = serializers.SerializerMethodField()
    expected_to_date = serializers.SerializerMethodField()
    cadence_status = serializers.SerializerMethodField()

    class Meta:
        model = MeetingSeries
        fields = [
            "id", "name", "description", "required_per_year", "owner", "owner_name",
            "active", "held_this_year", "expected_to_date", "cadence_status", "created_at",
        ]

    def _held(self, obj):
        return obj.minutes.filter(date__year=timezone.localdate().year).count()

    def get_held_this_year(self, obj):
        return self._held(obj)

    def get_expected_to_date(self, obj):
        """How many occurrences should have happened by now, pro-rated by month."""
        today = timezone.localdate()
        return min(obj.required_per_year, math.ceil(obj.required_per_year * today.month / 12))

    def get_cadence_status(self, obj):
        held = self._held(obj)
        if held >= obj.required_per_year:
            return "complete"
        return "on_track" if held >= self.get_expected_to_date(obj) else "behind"


# --------------------------------------------------------------------------- #
# Champion groups
# --------------------------------------------------------------------------- #
class GroupMemberSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.get_full_name", read_only=True, default="")
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = GroupMember
        fields = ["id", "group", "user", "user_name", "username", "department", "note", "added_at"]


class ChampionGroupSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    member_count = serializers.IntegerField(source="members.count", read_only=True)

    class Meta:
        model = ChampionGroup
        fields = ["id", "name", "purpose", "owner", "owner_name", "member_count", "created_at"]


# --------------------------------------------------------------------------
# Risk register
# --------------------------------------------------------------------------
from .models import Risk, RiskNote  # noqa: E402  (appended feature block)


class RiskNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True, default="")

    class Meta:
        model = RiskNote
        fields = ["id", "risk", "text", "author", "author_name", "created_at"]
        read_only_fields = ["author", "created_at"]


class RiskSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True, default="")
    control_label = serializers.CharField(source="control.control_id", read_only=True, default=None)
    control_framework = serializers.CharField(
        source="control.category.framework.key", read_only=True, default=None
    )
    score = serializers.IntegerField(read_only=True)
    rating = serializers.CharField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    note_count = serializers.SerializerMethodField()

    class Meta:
        model = Risk
        fields = [
            "id", "title", "description", "risk_type", "status", "treatment",
            "likelihood", "impact", "score", "rating",
            "owner", "owner_name", "control", "control_label", "control_framework",
            "due_date", "identified_on", "is_overdue",
            "jira_key", "mitigation_plan", "note_count",
            "created_by", "created_by_name", "created_at", "updated_at", "closed_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at", "closed_at"]
        extra_kwargs = {
            "likelihood": {"min_value": 1, "max_value": 5},
            "impact": {"min_value": 1, "max_value": 5},
        }

    def get_note_count(self, obj):
        annotated = getattr(obj, "note_count", None)
        return annotated if annotated is not None else obj.notes.count()

    def update(self, instance, validated_data):
        """Bookkeep closed_at when the status crosses the closed boundary."""
        new_status = validated_data.get("status", instance.status)
        if new_status == Risk.Status.CLOSED and instance.status != Risk.Status.CLOSED:
            validated_data["closed_at"] = timezone.now()
        elif new_status != Risk.Status.CLOSED and instance.status == Risk.Status.CLOSED:
            validated_data["closed_at"] = None
        return super().update(instance, validated_data)
