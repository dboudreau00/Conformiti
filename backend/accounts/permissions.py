"""Reusable DRF permission classes backed by Role capability flags."""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class _CapabilityPermission(BasePermission):
    """Grant read to any authenticated user; require a capability to write."""
    capability = None  # set in subclass

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return getattr(request.user, self.capability, False)


class CanManageUsers(_CapabilityPermission):
    capability = "can_manage_users"


class CanManageFrameworks(_CapabilityPermission):
    capability = "can_manage_frameworks"


class CanManageDocuments(_CapabilityPermission):
    capability = "can_manage_documents"


class CanManageFolders(_CapabilityPermission):
    capability = "can_manage_folders"


class IsAdministrator(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or u.can_manage_users))
