"""Workspaces: the organisations an installation serves (0.9.0).

Everyone may read their own; a superuser sees them all, creates new ones
and switches between them by sending ``X-Workspace: <slug>`` (the SPA
remembers the choice). There is no delete: a workspace is archived, which
refuses its people at sign-in and drops it out of every scheduled job, and
its rows stay where an operator can find them.
"""
from django.core.management import call_command
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import tenancy
from .models import Workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    users = serializers.SerializerMethodField()
    # Seed the built-in roles and the shipped frameworks into a new workspace
    # (the same `seed_frameworks --with-folders` a fresh install runs).
    with_frameworks = serializers.BooleanField(write_only=True, required=False, default=True)

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "is_active", "created_at", "users", "with_frameworks"]
        read_only_fields = ["created_at"]
        extra_kwargs = {"slug": {"required": False}}

    def get_users(self, obj):
        with tenancy.unscoped():
            return obj.users.filter(is_active=True).count()

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
        """The workspace this request is working in."""
        workspace = tenancy.request_workspace(request)
        if workspace is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        data = WorkspaceSerializer(workspace).data
        data["can_switch"] = bool(request.user.is_superuser)
        return Response(data)
