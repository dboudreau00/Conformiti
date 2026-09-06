"""Read-only audit trail API.

The log itself is written server-side by AuditLogMiddleware; this only exposes
it to the people who review it: administrators, auditors, and managers with
view-all. There is deliberately no write/update/delete surface — the trail is
immutable evidence.
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import AuditLog
from .serializers import AuditLogSerializer


class CanViewAuditLog(BasePermission):
    """Admins, auditors, and view-all managers may read the trail."""

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated
            and (u.can_manage_users or u.is_auditor or u.can_view_all)
        )


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("user").all()
    serializer_class = AuditLogSerializer
    permission_classes = [CanViewAuditLog]
    filterset_fields = ["action", "object_type", "user"]
    search_fields = [
        "object_type", "object_id", "detail", "ip_address",
        "user__username", "user__first_name", "user__last_name",
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            # Installation-level events (a failed sign-in for a username that
            # exists nowhere) belong to no workspace; the operator sees them.
            from accounts import tenancy

            with tenancy.unscoped():
                orphans = AuditLog.objects.filter(workspace__isnull=True)
            qs = qs | orphans
        days = self.request.query_params.get("days")
        if days:
            try:
                from datetime import timedelta
                from django.utils import timezone
                qs = qs.filter(timestamp__gte=timezone.now() - timedelta(days=int(days)))
            except (TypeError, ValueError):
                pass  # ignore a malformed value rather than 500
        return qs

    @action(detail=False)
    def facets(self, request):
        """Distinct values for the viewer's filter dropdowns.

        ``.order_by()`` with no arguments is essential: the model's Meta
        ordering (-timestamp) is otherwise added to the SELECT behind DISTINCT,
        which makes every row distinct and returns the same action once per
        entry — duplicating every option in the filter dropdowns."""
        base = AuditLog.objects.order_by()
        actions = sorted(set(base.values_list("action", flat=True).distinct()))
        types = sorted({t for t in base.values_list("object_type", flat=True).distinct() if t})
        users = (
            base.exclude(user__isnull=True)
            .values("user__id", "user__username").distinct().order_by("user__username")[:200]
        )
        return Response({
            "actions": actions,
            "object_types": types,
            "users": [{"id": u["user__id"], "username": u["user__username"]} for u in users],
        })
