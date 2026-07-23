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
from django.db import models
from django.utils import timezone

# --- access levels ----------------------------------------------------------
VIEW, EDIT, MANAGE = "view", "edit", "manage"
ACCESS_CHOICES = [(VIEW, "View"), (EDIT, "Edit"), (MANAGE, "Manage")]
ACCESS_RANK = {None: 0, VIEW: 1, EDIT: 2, MANAGE: 3}


def _add_months(d, months):
    """Add months to a date without a hard dependency on dateutil."""
    if relativedelta is not None:
        return d + relativedelta(months=months)
    # Fallback: approximate a month as 30 days.
    return d + timedelta(days=30 * months)


class Folder(models.Model):
    """A node in the document tree. Access is granted per folder and inherited."""
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
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
    def ancestors(self):
        node, chain = self.parent, []
        while node is not None:
            chain.append(node)
            node = node.parent
        return chain

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


class FolderPermission(models.Model):
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
        from django.core.exceptions import ValidationError
        if bool(self.role) == bool(self.user):
            raise ValidationError("Set exactly one of role or user.")

    def __str__(self):
        who = self.role or self.user
        return f"{who} -> {self.folder} ({self.access_level})"


def document_upload_path(instance, filename):
    folder_path = instance.folder.path if instance.folder_id else "unfiled"
    return f"documents/{folder_path}/{filename}"


class Document(models.Model):
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
    file = models.FileField(upload_to=document_upload_path)
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

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

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


class DocumentVersion(models.Model):
    """Immutable snapshot of a prior document file."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    file = models.FileField(upload_to="document_versions/")
    note = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        unique_together = ("document", "version")


class FormTemplate(models.Model):
    """A reusable blank form/policy template stored centrally for the org."""
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True, help_text="e.g. Policy, Register, Log")
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="form_templates/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name
