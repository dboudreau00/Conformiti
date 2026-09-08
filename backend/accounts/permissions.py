"""Reusable DRF permission classes backed by Role capability flags."""
from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_external_auditor(user):
    """The read-only outside party, as opposed to anyone employed here."""
    return bool(user and user.is_authenticated and user.is_auditor)


class NotExternalAuditor(BasePermission):
    """Refuse the external-auditor role outright.

    Pair it with any permission that grants read to *any* authenticated
    account. An external auditor holds an account on the client's
    installation, but their remit is the package issued to them, its request
    list, and the folders granted with it -- the rest of the programme (the
    risk register, the vendor file, the user directory, the control library,
    every other client's business) is the organisation's own.

    Deny by default: ``tests_auditor_surface.py`` walks the router and fails
    if a new collection appears that an auditor can read and nobody decided
    they should.
    """
    message = "That is outside an external auditor's access."

    def has_permission(self, request, view):
        return not is_external_auditor(request.user)


class _CapabilityPermission(BasePermission):
    """Grant read to any authenticated user; require a capability to write.

    "Any authenticated user" excludes the external auditor -- see
    ``NotExternalAuditor``. A subclass that is part of an audit sets
    ``allow_auditor``.
    """
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
