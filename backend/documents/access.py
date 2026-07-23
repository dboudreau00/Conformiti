"""Efficient folder-access resolution shared by the document API views."""
from .models import Folder, FolderPermission


def accessible_folder_ids(user):
    """
    Return the set of folder ids the user may at least view.

    A permission granted on a folder is inherited by all descendants, so we
    seed from directly granted / owned folders and expand downward with a
    small number of queries (rather than evaluating every folder in Python).
    """
    if not (user and user.is_authenticated):
        return set()
    if user.is_superuser or user.can_view_all or user.can_manage_folders:
        return set(Folder.objects.values_list("id", flat=True))

    seed = set(FolderPermission.objects.filter(user=user).values_list("folder_id", flat=True))
    if getattr(user, "role_id", None):
        seed |= set(
            FolderPermission.objects.filter(role_id=user.role_id).values_list("folder_id", flat=True)
        )
    seed |= set(Folder.objects.filter(owner=user).values_list("id", flat=True))

    accessible, frontier = set(seed), set(seed)
    while frontier:
        children = set(Folder.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        children -= accessible
        accessible |= children
        frontier = children
    return accessible
