from rest_framework.permissions import SAFE_METHODS, BasePermission


class FolderAccessPermission(BasePermission):
    """Read needs view, write needs edit, DELETE needs manage."""

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
    """Access derives from the document's folder: view reads, edit (or owning the document) writes, manage deletes.
    Ownership does not extend to deletion, so a control owner cannot make their own audit trail vanish."""

    def has_object_permission(self, request, view, obj):
        folder = obj.folder
        if request.method in SAFE_METHODS:
            return folder.can_view(request.user)
        # Before the owner short-circuit: owning a document must not lift an external auditor's view-only cap.
        from accounts.permissions import is_external_auditor

        if is_external_auditor(request.user):
            return False
        if request.method == "DELETE":
            return folder.can_manage(request.user)
        if obj.owner_id == request.user.id:
            return True
        return folder.can_edit(request.user)
