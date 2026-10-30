from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_external_auditor(user):
    return bool(user and user.is_authenticated and user.is_auditor)


class NotExternalAuditor(BasePermission):
    """Refuse the external-auditor role; pair it with any permission that grants read to every authenticated account.
    ``tests_auditor_surface.py`` fails on a new collection an auditor can read that nobody decided they should."""
    message = "That is outside an external auditor's access."

    def has_permission(self, request, view):
        return not is_external_auditor(request.user)


class _CapabilityPermission(BasePermission):
    """Read for any authenticated user but an external auditor (unless ``allow_auditor``); writing needs the named
    ``capability``."""
    capability = None  # set in subclass
    allow_auditor = False

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if not self.allow_auditor and is_external_auditor(request.user):
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
