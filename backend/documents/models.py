"""
Document management: folders, per-folder access control, documents with
review scheduling, version history, and a shared form-template library.
"""
from datetime import timedelta

try:
    # python-dateutil ships as a dependency of boto3/celery; guard anyway.
    from dateutil.relativedelta import relativedelta
except ImportError:  # pragma: no cover
    relativedelta = None

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.tenancy import TenantModel

# --- access levels ----------------------------------------------------------
VIEW, EDIT, MANAGE = "view", "edit", "manage"
ACCESS_CHOICES = [(VIEW, "View"), (EDIT, "Edit"), (MANAGE, "Manage")]
ACCESS_RANK = {None: 0, VIEW: 1, EDIT: 2, MANAGE: 3}

# Hard ceiling on tree depth. Real trees are 3-5 levels; the bound turns an
# accidental (or malicious) parent cycle into a clean error instead of an
# infinite loop in every access check.
MAX_FOLDER_DEPTH = 32

_FORBIDDEN_NAME_CHARS = set('/\\:*?"<>|\x00')


def validate_folder_name(value):
    """A folder name is a single path segment: it becomes a directory under
    MEDIA_ROOT, so separators, traversal and Windows-reserved characters are
    rejected here rather than discovered as a storage error on upload."""
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
    """Add months to a date without a hard dependency on dateutil."""
    if relativedelta is not None:
        return d + relativedelta(months=months)
    # Fallback: approximate a month as 30 days.
    return d + timedelta(days=30 * months)


class Folder(TenantModel):
    """A node in the document tree. Access is granted per folder and inherited."""
    tenant_parent = "parent"
    name = models.CharField(max_length=255, validators=[validate_folder_name])
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="folders",
    )
    # Stable identity for the seeded tree. Without these, seed_frameworks has to
    # match folders by their display name, so a framework version bump or a
    # reworded control title creates a second tree and orphans every document
    # filed under the old one.
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

    # -- hierarchy helpers --------------------------------------------------
    @property
    def is_seeded(self):
        """Part of the generated framework tree (root / category / control)."""
        return bool(self.is_framework_root or self.framework_id or self.category_id or self.control_id)

    def ancestors(self):
        """Parent chain, nearest first. Bounded and cycle-safe: a corrupted
        parent link raises instead of spinning forever."""
        node, chain, seen = self.parent, [], {self.id}
        while node is not None:
            if node.id in seen or len(chain) >= MAX_FOLDER_DEPTH:
                raise ValidationError(f"Folder {self.id} has a cyclic or over-deep parent chain.")
            seen.add(node.id)
            chain.append(node)
            node = node.parent
        return chain

    def would_cycle(self, new_parent):
        """True if setting ``new_parent`` would make this folder its own ancestor."""
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

    # -- access control -----------------------------------------------------
    def effective_access(self, user):
        """
        Return the highest access level ('manage'/'edit'/'view') the user has
        on this folder, or None. Resolution order:
          * superuser / can_manage_folders -> manage
          * can_view_all -> at least view
          * folder owner -> manage
          * explicit or inherited FolderPermission for the user or their role
          * auditors are capped at view
        """
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

    """Grants a role OR a specific user an access level on a folder (inherited)."""
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
    # max_length must comfortably exceed the deepest folder path
    # (documents/<framework>/<category>/<control>/<file>) or Django's storage
    # raises SuspiciousFileOperation when it can't fit the name in the default 100.
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
    # Tracks reminder lead-days already emailed so we don't send duplicates.
    reminders_sent = models.JSONField(default=list, blank=True)

    # --- malware scanning (documents/monitor.py). "clean" means clean by the
    # definitions in force at scanned_at; the sweep re-checks stored files
    # because signatures arrive after files do. A quarantined document stays
    # on disk for the investigation but no route serves its bytes.
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
        """Set next_review_date from last_reviewed + cadence."""
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
    """One row: what the malware scanner last said, and whether anyone has
    been told. Shared by every worker, so an outage is announced once."""
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
    tenant_parent = "document"

    """Immutable snapshot of a prior document file."""
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
    """A reusable blank form/policy template stored centrally for the org."""
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, help_text="e.g. Policy, Register, Log")
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="form_templates/", max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name
