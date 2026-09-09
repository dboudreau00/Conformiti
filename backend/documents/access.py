"""Efficient folder-access resolution shared by the document API views."""
from .models import ACCESS_RANK, MANAGE, VIEW, Folder, FolderPermission


def bulk_effective_access(user, folders):
    """``{folder_id: level}`` for every folder in ``folders``, in three queries.

    ``Folder.effective_access`` answers for one folder by walking its parent
    chain and querying the grants on it; the folder tree called it once per
    node, and a tree of two hundred folders was two hundred round trips
    plus the same again for document counts. This resolves the same answer
    for every folder at once: the parent map in one query, the grants that
    could apply in one more, and the walk in Python.

    The rules are the ones ``effective_access`` states, applied identically:
    superuser or the folders capability is manage everywhere; view-all is at
    least view; owning a folder is manage; a grant on a folder or any
    ancestor applies at its level; an external auditor is capped at view.
    """
    folders = list(folders)
    if not folders or not (user and user.is_authenticated):
        return {f.id: None for f in folders}
    if user.is_superuser or user.can_manage_folders:
        return {f.id: MANAGE for f in folders}

    parent_of = dict(Folder.objects.values_list("id", "parent_id"))
    clause = FolderPermission.objects.filter(user=user)
    if getattr(user, "role_id", None):
        from django.db.models import Q
        clause = FolderPermission.objects.filter(Q(user=user) | Q(role_id=user.role_id))
    granted = {}
    for folder_id, level in clause.values_list("folder_id", "access_level"):
        if ACCESS_RANK[level] > ACCESS_RANK[granted.get(folder_id)]:
            granted[folder_id] = level

    base = VIEW if user.can_view_all else None
    out = {}
    for folder in folders:
        best = MANAGE if folder.owner_id == user.id else base
        node, hops = folder.id, 0
        while node is not None and hops < 64:
            level = granted.get(node)
            if level and ACCESS_RANK[level] > ACCESS_RANK[best]:
                best = level
            node = parent_of.get(node)
            hops += 1
        if user.is_auditor and ACCESS_RANK[best] > ACCESS_RANK[VIEW]:
            best = VIEW
        out[folder.id] = best
    return out


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
