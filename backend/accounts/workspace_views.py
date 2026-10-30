"""Everyone reads their own workspace; a superuser sees all, creates them and switches with ``X-Workspace: <slug>``.
There is no delete: a workspace is archived, which refuses its people at sign-in and drops it out of every job."""
from django.core.management import call_command
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import tenancy
from .models import MAX_WEBHOOK_URL_LENGTH, Workspace, validate_webhook_url

# What any member may read of their organisation: enough to name it. The mailbox, chat channels and headcount stay the
# operator's, external auditors included (REVIEWS.md (0.9.5 review), S-1).
PUBLIC_FIELDS = ("id", "name", "slug", "is_active", "created_at", "can_switch")


class WorkspaceSerializer(serializers.ModelSerializer):
    users = serializers.SerializerMethodField()
    with_frameworks = serializers.BooleanField(write_only=True, required=False, default=True)
    # A webhook URL is a credential: write-only, never read back by anyone; *_configured says whether one is set.
    slack_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=MAX_WEBHOOK_URL_LENGTH,
        trim_whitespace=True)
    teams_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=MAX_WEBHOOK_URL_LENGTH,
        trim_whitespace=True)
    slack_configured = serializers.SerializerMethodField()
    teams_configured = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "is_active", "notification_email",
                  "slack_webhook_url", "teams_webhook_url", "created_at",
                  "slack_configured", "teams_configured", "users", "with_frameworks"]
        read_only_fields = ["created_at"]
        extra_kwargs = {"slug": {"required": False}}

    def validate_slack_webhook_url(self, value):
        return validate_webhook_url("slack", value, serializers.ValidationError)

    def validate_teams_webhook_url(self, value):
        return validate_webhook_url("teams", value, serializers.ValidationError)

    def get_slack_configured(self, obj):
        return bool((obj.slack_webhook_url or "").strip())

    def get_teams_configured(self, obj):
        return bool((obj.teams_webhook_url or "").strip())

    def get_users(self, obj):
        with tenancy.unscoped():
            return obj.users.filter(is_active=True).count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not getattr(user, "is_superuser", False):
            return {k: v for k, v in data.items() if k in PUBLIC_FIELDS}
        return data

    def validate(self, attrs):
        if not self.instance and not attrs.get("slug"):
            attrs["slug"] = slugify(attrs.get("name", ""))[:60]
        if "slug" in attrs and not attrs["slug"]:
            raise serializers.ValidationError({"slug": "Give the workspace a slug."})
        if self.instance and "slug" in attrs and attrs["slug"] != self.instance.slug \
                and self.instance.slug == tenancy.DEFAULT_SLUG:
            raise serializers.ValidationError({"slug": "The Default workspace keeps its slug."})
        return attrs


class IsSuperuserOrReadOwn(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if view.action in ("list", "retrieve", "current"):
            return True
        return request.user.is_superuser


class WorkspaceViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspaceSerializer
    permission_classes = [IsSuperuserOrReadOwn]
    http_method_names = ["get", "post", "patch", "head", "options"]
    search_fields = ["name", "slug"]

    def get_queryset(self):
        user = self.request.user
        qs = Workspace.objects.all()
        if user.is_superuser:
            return qs
        return qs.filter(pk=user.workspace_id) if user.workspace_id else qs.none()

    def perform_create(self, serializer):
        with_frameworks = serializer.validated_data.pop("with_frameworks", True)
        with transaction.atomic():
            workspace = serializer.save()
            with tenancy.scoped(workspace):
                # Roles are always seeded: nobody can be invited without one.
                args = ["--with-folders"] if with_frameworks else ["--roles-only"]
                call_command("seed_frameworks", *args, workspace=workspace.slug, verbosity=0)

    def perform_update(self, serializer):
        serializer.validated_data.pop("with_frameworks", None)
        instance = serializer.instance
        if serializer.validated_data.get("is_active") is False:
            if instance.pk == tenancy.current_id():
                raise PermissionDenied("Switch to another workspace before archiving this one.")
            if instance.slug == tenancy.DEFAULT_SLUG:
                raise PermissionDenied("The Default workspace cannot be archived.")
        serializer.save()

    @action(detail=False, methods=["get"])
    def current(self, request):
        workspace = tenancy.request_workspace(request)
        if workspace is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        # With the context, so the serializer trims the operator-only fields for everyone but a superuser.
        data = WorkspaceSerializer(workspace, context=self.get_serializer_context()).data
        data["can_switch"] = bool(request.user.is_superuser)
        return Response(data)
