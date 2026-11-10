from rest_framework.permissions import SAFE_METHODS, BasePermission


class FolderAccessPermission(BasePermission):
    """Read needs view, write needs edit, DELETE needs manage."""

    def has_object_permission(self, request, view, obj):
        access = obj.effective_access(request.user)
        if access is None:
            self.message = "That folder is not available to you."
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            self.message = "You need manage access on a folder to delete it."
            return obj.can_manage(request.user)
        self.message = "You need edit access to this folder."
        return obj.can_edit(request.user)


class DocumentAccessPermission(BasePermission):
    """Access derives from the document's folder: view reads, edit (or owning the document) writes, manage deletes.
    Ownership does not extend to deletion, so a control owner cannot make their own audit trail vanish."""

    def has_object_permission(self, request, view, obj):
        folder = obj.folder
        if request.method in SAFE_METHODS:
            self.message = "That document is not available to you."
            return folder.can_view(request.user)
        # Before the owner short-circuit: owning a document must not lift an external auditor's view-only cap.
        from accounts.permissions import AUDITOR_REFUSED, is_external_auditor

        if is_external_auditor(request.user):
            self.message = AUDITOR_REFUSED
            return False
        if request.method == "DELETE":
            self.message = "You need manage access on a document's folder to delete it."
            return folder.can_manage(request.user)
        if obj.owner_id == request.user.id:
            return True
        self.message = "Only a document's owner, or people with edit access to its folder, can change it."
        return folder.can_edit(request.user)
