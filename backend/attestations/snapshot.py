"""
Taking the point-in-time copies a package is made of.

Nothing here reads a live row at display time. Controls are renamed, documents
get new versions and people leave, and none of that may change what a sealed
package says was handed over.
"""
import hashlib

from django.utils import timezone

from .models import PackageControl, PackageEvidence


def _full_name(user):
    if not user:
        return ""
    return (user.get_full_name() or user.get_username())[:200]


def digest_and_size(file_field):
    """SHA-256 and byte count of a stored file, read in chunks.

    Returns ``(None, 0)`` when the file is missing rather than raising: a
    package whose evidence has vanished must still be inspectable, and the seal
    guard is where that becomes an error.
    """
    if not file_field:
        return None, 0
    try:
        handle = file_field.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        return None, 0
    total, sha = 0, hashlib.sha256()
    try:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            total += len(chunk)
            sha.update(chunk)
    finally:
        handle.close()
    return sha.hexdigest(), total


def snapshot_control(package, control, user, note="", ordinal=0):
    """Copy a control into the package as it stands right now."""
    category = control.category
    framework = category.framework
    return PackageControl.objects.create(
        package=package, control=control, ordinal=ordinal,
        framework_key=framework.key, framework_name=framework.name,
        framework_version=framework.version,
        category_key=category.key, category_name=category.name,
        control_ref=control.control_id, title=control.title,
        objective=control.objective or "",
        mgmt_status=control.status,
        mgmt_status_display=control.get_status_display(),
        owner_name=_full_name(control.owner),
        note=note[:255], included_by_name=_full_name(user),
    )


def pin_document(package_control, document, user, link=None, ordinal=0, **extra):
    """Pin one document into a control row, hashing it as it stands.

    ``link`` is the ``ControlEvidence`` row, if the document is being pinned
    because it is already linked to the control. Its ``linked_by`` and
    ``created_at`` are carried forward, because who asserted that this artefact
    evidences this control, and when, is itself audit evidence.
    """
    sha, size = digest_and_size(document.file)
    return PackageEvidence.objects.create(
        package_control=package_control, document=document, ordinal=ordinal,
        document_name=document.name[:255],
        pinned_version=document.version,
        storage_name=(document.file.name or "").rsplit("/", 1)[-1][:255],
        storage_path=(document.file.name or "")[:500],
        size_bytes=size,
        content_sha256=sha or "",
        doc_status=document.status,
        doc_status_display=document.get_status_display(),
        last_reviewed=document.last_reviewed,
        next_review_date=document.next_review_date,
        covers_from=extra.get("covers_from"),
        covers_to=extra.get("covers_to"),
        is_population=bool(extra.get("is_population")),
        evidence_note=str(extra.get("evidence_note", ""))[:255],
        linked_by_name=_full_name(getattr(link, "linked_by", None)),
        evidence_linked_at=getattr(link, "created_at", None),
        pinned_by=user, pinned_by_name=_full_name(user),
    )


def pinned_file(row):
    """The file a pinned row stands for, as ``(file, archived_version)``.

    The document's own file while it is still the one pinned; after a new
    version, the archived version that kept it. Reading the document's current
    file instead would serve bytes the package never sealed while the package
    still showed the sealed digest. ``(None, None)`` when neither holds it: a
    file the package did not seal is not served in its place.
    """
    document = row.document
    if document is None or not document.file:
        return None, None
    # A row with no storage_path names no file, so the document's own is all
    # there is to go on.
    if not row.storage_path or document.file.name == row.storage_path:
        return document.file, None
    archived = document.versions.filter(file=row.storage_path).first()
    if archived is None:
        return None, None
    return archived.file, archived.version


def verify_pins(package):
    """Re-hash every pinned artefact. Returns the rows that no longer match.

    While the package is a draft the question is whether each document still
    holds what was pinned, so a new version means refresh or unpin before
    sealing. Once it is sealed the question is whether the package can still
    produce what it sealed (pinned_file), which a later version of the
    document does not change.

    Each entry is ``{"item", "control_ref", "document", "expected", "actual"}``
    where ``actual`` is ``None`` if the file has gone.
    """
    drifted = []
    sealed = not package.is_open
    rows = PackageEvidence.objects.filter(
        package_control__package=package
    ).select_related("package_control", "document")
    for row in rows:
        current = None
        if sealed:
            source, _ = pinned_file(row)
        else:
            source = row.document.file if row.document and row.document.file else None
        if source:
            current, _ = digest_and_size(source)
        if current != row.content_sha256:
            drifted.append({
                "item": row.pk,
                "control_ref": row.package_control.control_ref,
                "document": row.document_name,
                "expected": row.content_sha256,
                "actual": current,
            })
    return drifted


def stamp(instance, user, prefix):
    """Record who did something and when, on the `<prefix>_by[_name]/_at` triple."""
    setattr(instance, f"{prefix}_by", user)
    setattr(instance, f"{prefix}_by_name", _full_name(user))
    setattr(instance, f"{prefix}_at", timezone.now())
    return instance
