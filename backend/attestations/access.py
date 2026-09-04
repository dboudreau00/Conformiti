"""
The only place in Conformiti where folder permissions are bypassed.

The rule, in one sentence:

    An external auditor may read exactly the rows and bytes pinned into a
    sealed package that has been issued to them, for as long as the grant is
    live, and nothing else. Packaging cannot disclose anything the packager
    could not already read.

Keeping every verb in one small module is the point. A bypass scattered across
viewsets is a bypass nobody can audit.
"""
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from documents.access import accessible_folder_ids

_PIN_DENIED = "You can only add evidence from folders you can already see."


def can_assemble(user):
    """Create a package, pin or unpin evidence, seal, issue, withdraw."""
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or user.can_manage_frameworks)
    )


def readable_packages(user):
    """Every package this user may read the metadata, rows AND bytes of.

    Read-of-metadata and read-of-bytes are deliberately the same set. Splitting
    them would be false comfort: the evidence index already names every
    document, and an index the caller cannot open is itself a disclosure.

    Deliberately NOT keyed on ``can_manage_documents``. The shipped "Control
    Owner" role is exactly that flag and confers no cross-folder document read
    today; it must not gain one here.
    """
    from .models import EvidencePackage, PackageGrant

    if not (user and user.is_authenticated):
        return EvidencePackage.objects.none()
    if user.is_superuser or (user.can_manage_frameworks and user.can_view_all):
        return EvidencePackage.objects.all()
    if user.can_manage_frameworks:
        # A frameworks role without view-all reads only what it assembled,
        # which by construction holds only folders it could already see.
        return EvidencePackage.objects.filter(created_by=user)
    return EvidencePackage.objects.filter(
        pk__in=PackageGrant.objects.filter(
            user=user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
            package__status=EvidencePackage.Status.SEALED,
        ).values("package_id")
    )


def can_read(user, package):
    """Object-level twin of readable_packages(). Expressed in terms of it so
    the two can never drift apart."""
    return readable_packages(user).filter(pk=package.pk).exists()


def live_grant(user, package):
    """The grant authorising this user to write conclusions, or None.

    Re-checks ``is_active`` and the LIVE role flag on every call, so demoting
    an account out of the Auditor role or deactivating it takes effect on the
    next request rather than at the next expiry.
    """
    from .models import EvidencePackage, PackageGrant

    if not (user and user.is_authenticated and user.is_active and user.is_auditor):
        return None
    return PackageGrant.objects.filter(
        package=package, user=user,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
        package__status=EvidencePackage.Status.SEALED,
    ).first()


def assert_pinnable(user, document):
    """You cannot disclose what you cannot see.

    Mirrors ``compliance.views.ControlEvidenceViewSet.perform_create``: a
    packager must hold the frameworks capability *and* be able to see the
    document's folder. Without this check the packaging step becomes a way to
    launder access to folders the packager was never granted.
    """
    if not can_assemble(user):
        raise PermissionDenied(_PIN_DENIED)
    if document.folder_id not in accessible_folder_ids(user):
        raise PermissionDenied(_PIN_DENIED)
    return document
