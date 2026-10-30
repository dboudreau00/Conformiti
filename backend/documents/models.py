from datetime import timedelta

try:
    from dateutil.relativedelta import relativedelta
except ImportError:  # pragma: no cover
    relativedelta = None

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.tenancy import TenantModel

VIEW, EDIT, MANAGE = "view", "edit", "manage"
ACCESS_CHOICES = [(VIEW, "View"), (EDIT, "Edit"), (MANAGE, "Manage")]
ACCESS_RANK = {None: 0, VIEW: 1, EDIT: 2, MANAGE: 3}

# Ceiling on tree depth: turns a parent cycle into an error instead of an endless loop in every access check.
MAX_FOLDER_DEPTH = 32

_FORBIDDEN_NAME_CHARS = set('/\\:*?"<>|\x00')


def validate_folder_name(value):
    """A folder name becomes a directory under MEDIA_ROOT, so it must be a single path segment."""
    name = (value or "").strip()
    if not name:
        raise ValidationError("Folder name cannot be blank.")
    if name in (".", ".."):
        raise ValidationError("Folder name cannot be '.' or '..'.")
    if any(ch in _FORBIDDEN_NAME_CHARS for ch in name) or any(ord(ch) < 32 for ch in name):
        raise ValidationError('Folder name cannot contain / \\ : * ? " < > | or control characters.')
    if name.endswith(".") or name != value:
        raise ValidationError("Folder name cannot start or end with whitespace or end with a dot.")


def _add_months(d, months):
    if relativedelta is not None:
        return d + relativedelta(months=months)
    # Fallback: approximate a month as 30 days.
    return d + timedelta(days=30 * months)


class Folder(TenantModel):
    tenant_parent = "parent"
    name = models.CharField(max_length=255, validators=[validate_folder_name])
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="folders",
    )
    # Stable identity for the seeded tree: seed_frameworks matches on these, not on display names.
    framework = models.ForeignKey(
        "compliance.Framework", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="folders",
    )
    category = models.ForeignKey(
        "compliance.ControlCategory", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="folders",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_folders",
    )
    is_framework_root = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["parent__id", "name"]
        unique_together = ("parent", "name")

    def __str__(self):
        return self.name

    @property
    def is_seeded(self):
        """Part of the generated framework tree (root / category / control)."""
        return bool(self.is_framework_root or self.framework_id or self.category_id or self.control_id)

    def ancestors(self):
        """Parent chain, nearest first. Raises on a cycle or an over-deep chain instead of looping forever."""
        node, chain, seen = self.parent, [], {self.id}
        while node is not None:
            if node.id in seen or len(chain) >= MAX_FOLDER_DEPTH:
                raise ValidationError(f"Folder {self.id} has a cyclic or over-deep parent chain.")
            seen.add(node.id)
            chain.append(node)
            node = node.parent
        return chain

    def would_cycle(self, new_parent):
        node, hops = new_parent, 0
        while node is not None:
            if node.id == self.id:
                return True
            hops += 1
            if hops > MAX_FOLDER_DEPTH:
                return True
            node = node.parent
        return False

    @property
    def path(self):
        parts = [f.name for f in reversed(self.ancestors())] + [self.name]
        return "/".join(parts)

    def effective_access(self, user):
        """Highest of: manage for a superuser, folder manager or owner; view for view-all; grants on this folder or an
        ancestor to the user or their role. Auditors are capped at view. ``bulk_effective_access`` must agree."""
        if not (user and user.is_authenticated):
            return None
        if user.is_superuser or user.can_manage_folders:
            return MANAGE
        best = None
        if user.can_view_all:
            best = VIEW
        if self.owner_id == user.id:
            best = MANAGE

        folder_ids = [self.id] + [a.id for a in self.ancestors()]
        clause = models.Q(user=user)
        if getattr(user, "role_id", None):
            clause |= models.Q(role_id=user.role_id)
        perms = FolderPermission.objects.filter(folder_id__in=folder_ids).filter(clause)
        for p in perms:
            if ACCESS_RANK[p.access_level] > ACCESS_RANK[best]:
                best = p.access_level

        if user.is_auditor and ACCESS_RANK[best] > ACCESS_RANK[VIEW]:
            best = VIEW
        return best

    def can_view(self, user):
        return ACCESS_RANK[self.effective_access(user)] >= ACCESS_RANK[VIEW]

    def can_edit(self, user):
        return ACCESS_RANK[self.effective_access(user)] >= ACCESS_RANK[EDIT]

    def can_manage(self, user):
        return ACCESS_RANK[self.effective_access(user)] >= ACCESS_RANK[MANAGE]


class FolderPermission(TenantModel):
    tenant_parent = "folder"
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="permissions")
    role = models.ForeignKey(
        "accounts.Role", null=True, blank=True, on_delete=models.CASCADE, related_name="folder_permissions"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="folder_permissions",
    )
    access_level = models.CharField(max_length=10, choices=ACCESS_CHOICES, default=VIEW)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("folder", "role", "user", "access_level")]

    def clean(self):
        if bool(self.role) == bool(self.user):
            raise ValidationError("Set exactly one of role or user.")

    def __str__(self):
        who = self.role or self.user
        return f"{who} -> {self.folder} ({self.access_level})"


def document_upload_path(instance, filename):
    folder_path = instance.folder.path if instance.folder_id else "unfiled"
    return f"documents/{folder_path}/{filename}"


class Document(TenantModel):
    tenant_parent = "folder"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In review"
        APPROVED = "approved", "Approved"
        EXPIRED = "expired", "Expired"

    class Cadence(models.TextChoices):
        NONE = "none", "No review"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        SEMIANNUAL = "semiannual", "Every 6 months"
        ANNUAL = "annual", "Annual"
        BIENNIAL = "biennial", "Every 2 years"

    CADENCE_MONTHS = {
        "monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12, "biennial": 24,
    }

    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="documents")
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="documents",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # max_length must exceed the deepest folder path, or storage raises SuspiciousFileOperation.
    file = models.FileField(upload_to=document_upload_path, max_length=500)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_documents",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    review_cadence = models.CharField(max_length=12, choices=Cadence.choices, default=Cadence.ANNUAL)
    last_reviewed = models.DateField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reminders_sent = models.JSONField(default=list, blank=True)

    # Malware scan state (documents/monitor.py): "clean" holds only for the definitions in force at scanned_at.
    class Scan(models.TextChoices):
        UNSCANNED = "unscanned", "Not scanned"
        CLEAN = "clean", "Clean"
        INFECTED = "infected", "Infected"
        ERROR = "error", "Could not be scanned"

    scan_status = models.CharField(max_length=10, choices=Scan.choices, default=Scan.UNSCANNED)
    scan_signature = models.CharField(max_length=200, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    quarantined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    @property
    def is_quarantined(self):
        return self.quarantined_at is not None

    def compute_next_review(self):
        months = self.CADENCE_MONTHS.get(self.review_cadence)
        base = self.last_reviewed or timezone.now().date()
        self.next_review_date = _add_months(base, months) if months else None
        return self.next_review_date

    @property
    def is_overdue(self):
        return bool(self.next_review_date and self.next_review_date < timezone.now().date())

    @property
    def days_until_review(self):
        if not self.next_review_date:
            return None
        return (self.next_review_date - timezone.now().date()).days


class ScannerStatus(models.Model):
    """One row shared by every worker, so an outage is announced once."""
    reachable = models.BooleanField(default=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    last_ok_at = models.DateTimeField(null=True, blank=True)
    down_since = models.DateTimeField(null=True, blank=True)
    alerted_down_at = models.DateTimeField(null=True, blank=True)
    alerted_up_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "scanner status"

    def __str__(self):
        return "scanner " + ("up" if self.reachable else "down")

    @classmethod
    def load(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row


class DocumentVersion(TenantModel):
    """Immutable snapshot of a prior document file."""
    tenant_parent = "document"
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    file = models.FileField(upload_to="document_versions/", max_length=500)
    note = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        unique_together = ("document", "version")


class FormTemplate(TenantModel):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, help_text="e.g. Policy, Register, Log")
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="form_templates/", max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name
