"""Serializers for the document-management API."""
from rest_framework import serializers

from .models import (
    Document,
    DocumentVersion,
    Folder,
    FolderPermission,
    FormTemplate,
)


class FolderPermissionSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True, default=None)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True, default=None)

    class Meta:
        model = FolderPermission
        fields = ["id", "folder", "role", "role_name", "user", "user_name", "access_level", "granted_at"]

    def validate(self, attrs):
        # Fall back to the existing instance for fields absent from a partial
        # update, so a PATCH that touches only access_level (or moves the grant
        # to another folder) still passes the "exactly one of role/user" rule.
        role = attrs.get("role", getattr(self.instance, "role", None))
        user = attrs.get("user", getattr(self.instance, "user", None))
        if bool(role) == bool(user):
            raise serializers.ValidationError("Set exactly one of role or user.")
        return attrs


class FolderSerializer(serializers.ModelSerializer):
    path = serializers.CharField(read_only=True)
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    control_id = serializers.CharField(source="control.control_id", read_only=True, default=None)
    child_count = serializers.IntegerField(source="children.count", read_only=True)
    document_count = serializers.IntegerField(source="documents.count", read_only=True)
    my_access = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = [
            "id", "name", "parent", "path", "control", "control_id", "owner",
            "owner_name", "is_framework_root", "child_count", "document_count",
            "my_access", "created_at", "updated_at",
        ]
        read_only_fields = ["is_framework_root"]

    def get_my_access(self, obj):
        request = self.context.get("request")
        return obj.effective_access(request.user) if request else None


class DocumentVersionSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True, default="")

    class Meta:
        model = DocumentVersion
        fields = ["id", "version", "file", "note", "uploaded_by", "uploaded_by_name", "created_at"]


class DocumentSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    folder_path = serializers.CharField(source="folder.path", read_only=True)
    control_id = serializers.CharField(source="control.control_id", read_only=True, default=None)
    is_overdue = serializers.BooleanField(read_only=True)
    days_until_review = serializers.IntegerField(read_only=True)
    satisfies = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id", "name", "description", "file", "folder", "folder_path",
            "control", "control_id", "owner", "owner_name", "status",
            "review_cadence", "last_reviewed", "next_review_date",
            "is_overdue", "days_until_review", "version",
            "created_by", "created_at", "updated_at", "satisfies",
        ]
        read_only_fields = ["version", "created_by", "next_review_date"]

    def get_satisfies(self, obj):
        """Controls this document is linked to as evidence (reverse mapping).
        Relies on the view prefetching control_links to stay one query."""
        return [
            {
                "link_id": link.id,
                "control": link.control.id,
                "label": link.control.control_id,
                "title": link.control.title,
                "framework": link.control.category.framework.key,
            }
            for link in obj.control_links.all()
        ]


class FormTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormTemplate
        fields = ["id", "name", "category", "description", "file", "created_at"]
