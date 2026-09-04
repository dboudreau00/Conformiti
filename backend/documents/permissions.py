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
        if request.method == "DELETE":
            return folder.can_manage(request.user)
        if obj.owner_id == request.user.id:
            return True
        return folder.can_edit(request.user)
