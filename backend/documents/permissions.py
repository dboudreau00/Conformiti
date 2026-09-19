"""Object-level permissions for folders and documents based on folder access."""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import EDIT, MANAGE, VIEW


class FolderAccessPermission(BasePermission):
    """Read requires view; write requires edit; delete/permissions require manage."""

    def has_object_permission(self, request, view, obj):
        access = obj.effective_access(request.user)
        if access is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return obj.can_manage(request.user)
        return obj.can_edit(request.user)


class DocumentAccessPermission(BasePermission):
    """Document access derives from its folder.

    * read      -> view on the folder
    * edit      -> edit on the folder, or being the document's owner
    * delete    -> manage on the folder. Ownership does *not* extend to
                   deletion: evidence removal is a manage-level act so a
                   control owner cannot make their own audit trail vanish.
    """

    def has_object_permission(self, request, view, obj):
        folder = obj.folder
        if request.method in SAFE_METHODS:
            return folder.can_view(request.user)
        # Before the owner short-circuit. Folder writes go through
        # effective_access, which caps an external auditor at view; document
        # writes went round it, so an auditor who had been made the owner of a
        # document in a granted folder could edit its name, status and
        # description (0.9.5h, L-5).
        from accounts.permissions import is_external_auditor

        if is_external_auditor(request.user):
            return False
        if request.method == "DELETE":
            return folder.can_manage(request.user)
        if obj.owner_id == request.user.id:
            return True
        return folder.can_edit(request.user)
