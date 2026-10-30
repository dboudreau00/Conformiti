"""The only place folder permissions are bypassed: an external auditor reads exactly the rows and bytes pinned into
a sealed package issued to them, while the grant is live, and nothing else."""
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
    """Packages this user may read metadata, rows AND bytes of: one set, as an index the caller cannot open is itself a
    disclosure. Never keyed on ``can_manage_documents``: Control Owner holds it and has no cross-folder read."""
    from .models import EvidencePackage, PackageGrant

    if not (user and user.is_authenticated):
        return EvidencePackage.objects.none()
    if user.is_superuser or (user.can_manage_frameworks and user.can_view_all):
        return EvidencePackage.objects.all()
    if user.can_manage_frameworks:
        # Without view-all, only what it assembled: by construction folders it could already see.
        return EvidencePackage.objects.filter(created_by=user)
    if not (user.is_active and user.is_auditor):
        # Matches live_grant(): a grant needs an active Auditor account, so demotion cuts reads off at once.
        return EvidencePackage.objects.none()
    return EvidencePackage.objects.filter(
        pk__in=PackageGrant.objects.filter(
            user=user,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
            package__status=EvidencePackage.Status.SEALED,
        ).values("package_id")
    )


def can_read(user, package):
    """Object-level twin of readable_packages(), defined through it so the two cannot drift."""
    return readable_packages(user).filter(pk=package.pk).exists()


def live_grant(user, package):
    """The grant authorising this user to write conclusions, or None. Re-checks ``is_active`` and the live Auditor
    role on every call, so demotion or deactivation bites on the next request, not at expiry."""
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
    """You cannot disclose what you cannot see: without this, packaging launders access to folders the packager was
    never granted. Mirrors ``compliance.views.ControlEvidenceViewSet.perform_create``."""
    if not can_assemble(user):
        raise PermissionDenied(_PIN_DENIED)
    if document.folder_id not in accessible_folder_ids(user):
        raise PermissionDenied(_PIN_DENIED)
    return document


def readable_pbc_requests(user):
    """The request list this user may see: the second folder-permission bypass. Whoever reads a package reads its
    requests; the person a line is ASSIGNED to sees that line and its attachments with no package access."""
    from django.db.models import Q

    from .models import PbcRequest

    if not (user and user.is_authenticated):
        return PbcRequest.objects.none()
    if user.is_auditor:
        # Auditors read through their GRANT only: the assignee arm would outlive revocation and expiry, and they could
        # put themselves on a line to keep access.
        return PbcRequest.objects.filter(package__in=readable_packages(user)).distinct()
    return PbcRequest.objects.filter(
        Q(package__in=readable_packages(user)) | Q(assignee=user)
    ).distinct()
