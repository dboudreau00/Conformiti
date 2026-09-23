"""Serializers for the document-management API."""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    Document,
    DocumentVersion,
    Folder,
    FolderPermission,
    FormTemplate,
    validate_folder_name,
)
from .downloads import download_filename
from .uploads import validate_upload


def person_name(user):
    """Full name, or the username for an account that has none (every account
    createsuperuser makes, whose documents otherwise showed no owner at all).
    The same rule as User.__str__; "" for nobody."""
    return (user.get_full_name() or user.get_username()) if user else ""


class PersonNameField(serializers.ReadOnlyField):
    """A related person's name by the ``person_name`` rule, "" for nobody:
    ``owner_name = PersonNameField("owner")``.

    It reads the whole row (source "*") and follows the relation itself.
    With the relation as its source, DRF would answer null for an empty one
    without asking the field, where these names have always been ""."""

    def __init__(self, relation, **kwargs):
        self.relation = relation
        super().__init__(source="*", **kwargs)

    def to_representation(self, obj):
        return person_name(getattr(obj, self.relation, None))


class FolderPermissionSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True, default=None)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True, default=None)
    username = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = FolderPermission
        fields = [
            "id", "folder", "role", "role_name", "user", "user_name", "username",
            "access_level", "granted_at",
        ]

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
    owner_name = serializers.SerializerMethodField()
    control_id = serializers.CharField(source="control.control_id", read_only=True, default=None)
    child_count = serializers.IntegerField(source="children.count", read_only=True)
    document_count = serializers.IntegerField(source="documents.count", read_only=True)
    my_access = serializers.SerializerMethodField()
    is_seeded = serializers.BooleanField(read_only=True)

    class Meta:
        model = Folder
        fields = [
            "id", "name", "parent", "path", "control", "control_id", "owner",
            "owner_name", "is_framework_root", "is_seeded", "child_count", "document_count",
            "my_access", "created_at", "updated_at",
        ]
        read_only_fields = ["is_framework_root", "control"]

    def get_owner_name(self, obj):
        return person_name(obj.owner)

    def get_my_access(self, obj):
        request = self.context.get("request")
        return obj.effective_access(request.user) if request else None

    def validate_name(self, value):
        try:
            validate_folder_name(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def validate_parent(self, parent):
        # A folder can't be moved under itself or any of its descendants —
        # that would corrupt the tree and hang every access check on it.
        if self.instance is not None and parent is not None:
            if parent.pk == self.instance.pk or self.instance.would_cycle(parent):
                raise serializers.ValidationError(
                    "A folder cannot be moved inside itself or one of its subfolders."
                )
        return parent


class DocumentVersionSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentVersion
        fields = ["id", "version", "note", "uploaded_by", "uploaded_by_name",
                  "created_at", "download_url"]

    def get_uploaded_by_name(self, obj):
        return person_name(obj.uploaded_by)

    def get_download_url(self, obj):
        return f"/documents/{obj.document_id}/versions/{obj.pk}/download/"


class DocumentSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    folder_path = serializers.CharField(source="folder.path", read_only=True)
    control_id = serializers.CharField(source="control.control_id", read_only=True, default=None)
    is_overdue = serializers.BooleanField(read_only=True)
    days_until_review = serializers.IntegerField(read_only=True)
    satisfies = serializers.SerializerMethodField()
    # Uploadable, never readable. Serializing the storage URL would publish a
    # second route to the bytes that no permission check stands in front of --
    # and upload paths are derived predictably from the folder tree, so the
    # value is a working locator for anyone who sees it. Read through
    # `download_url`, which the API authorises and records.
    file = serializers.FileField(write_only=True)
    download_url = serializers.SerializerMethodField()
    # The name the download is saved under, as the server sends it (display
    # name plus the stored file's extension). Carries no part of the path.
    download_name = serializers.SerializerMethodField()
    quarantined = serializers.BooleanField(source="is_quarantined", read_only=True)

    class Meta:
        model = Document
        fields = [
            "id", "name", "description", "file", "download_url", "download_name",
            "folder", "folder_path",
            "control", "control_id", "owner", "owner_name", "status",
            "review_cadence", "last_reviewed", "next_review_date",
            "is_overdue", "days_until_review", "version",
            "scan_status", "scan_signature", "scanned_at", "quarantined",
            "created_by", "created_at", "updated_at", "satisfies",
        ]
        read_only_fields = ["version", "created_by", "next_review_date",
                            "scan_status", "scan_signature", "scanned_at"]

    def get_download_url(self, obj):
        return f"/documents/{obj.pk}/download/" if obj.file else None

    def get_download_name(self, obj):
        return download_filename(obj.name, obj.file.name) if obj.file else None

    def get_owner_name(self, obj):
        return person_name(obj.owner)

    def validate_file(self, value):
        return validate_upload(value)

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("A document name is required.")
        return value

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
    # Same reasoning as DocumentSerializer.file.
    file = serializers.FileField(write_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = FormTemplate
        fields = ["id", "name", "category", "description", "file", "download_url", "created_at"]

    def get_download_url(self, obj):
        return f"/form-templates/{obj.pk}/download/" if obj.file else None

    def validate_file(self, value):
        return validate_upload(value)
