from django.conf import settings
from django.db import models

from accounts.tenancy import TenantModel


class Framework(TenantModel):
    key = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=60, blank=True)
    authority = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "key"], name="uniq_framework_key_per_workspace"),
        ]

    def __str__(self):
        return f"{self.name} {self.version}".strip()


class ControlCategory(TenantModel):
    tenant_parent = "framework"
    framework = models.ForeignKey(Framework, on_delete=models.CASCADE, related_name="categories")
    key = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["framework", "order", "key"]
        unique_together = ("framework", "key")
        verbose_name_plural = "control categories"

    def __str__(self):
        return self.name


class Control(TenantModel):
    tenant_parent = "category"

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        IMPLEMENTED = "implemented", "Implemented"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    category = models.ForeignKey(ControlCategory, on_delete=models.CASCADE, related_name="controls")
    control_id = models.CharField(max_length=40)
    # Place in the framework's data file (no sort of control_id suits every standard); 0 means unplaced.
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255)
    objective = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_controls",
    )

    # Who and when are stored beside the date: audit logging records field names only, so a backdated
    # last_tested_on would otherwise leave no trace of who set it.
    last_tested_on = models.DateField(null=True, blank=True)
    test_interval_days = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="How often this control should be retested. Blank uses the site default.",
    )
    last_tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="controls_tested",
    )
    last_tested_recorded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["category", "order", "control_id"]
        unique_together = ("category", "control_id")

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            # Materialised: Django accepts any iterable, and it is read twice below.
            update_fields = kwargs["update_fields"] = list(update_fields)
        if self._needs_place(update_fields):
            self.order = self.next_order(self.category_id)
            if update_fields is not None:
                update_fields.append("order")
        super().save(*args, **kwargs)

    def _needs_place(self, update_fields):
        """A new unplaced control, or one moved to another category without a new place, goes last in its category.
        Moved-ness is read from the row, not remembered from the load: a deferred field or partial refresh lies."""
        if self._state.adding:
            return not self.order
        if update_fields is not None and (
                "order" in update_fields
                or not {"category", "category_id"} & set(update_fields)):
            return False
        stored = (type(self)._base_manager.filter(pk=self.pk)
                  .values_list("category_id", "order").first())
        if stored is None:
            return not self.order
        category_id, order = stored
        return category_id != self.category_id and order == self.order

    @classmethod
    def next_order(cls, category_id):
        """Unscoped on purpose: the category already names the workspace, and a seeder may run with none active."""
        last = (cls._base_manager.filter(category_id=category_id)
                .aggregate(last=models.Max("order"))["last"])
        return (last or 0) + 1

    @property
    def framework(self):
        return self.category.framework

    def __str__(self):
        return f"{self.control_id} - {self.title}"


class ControlMapping(TenantModel):
    theme = models.CharField(max_length=200)
    controls = models.ManyToManyField(Control, related_name="mappings")

    class Meta:
        ordering = ["theme"]

    def __str__(self):
        return self.theme


class ControlEvidence(TenantModel):
    tenant_parent = "control"

    control = models.ForeignKey(
        Control, on_delete=models.CASCADE, related_name="evidence_links"
    )
    document = models.ForeignKey(
        "documents.Document", on_delete=models.CASCADE, related_name="control_links"
    )
    note = models.CharField(max_length=255, blank=True)
    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="evidence_links_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["control", "-created_at"]
        unique_together = ("control", "document")
        verbose_name_plural = "control evidence"

    def __str__(self):
        return f"{self.control.control_id} <- {self.document.name}"


class Responsibility(TenantModel):
    """One RACI row; the party is a user or a vendor. ``Control.owner`` is an implicit Accountable when none exists."""

    class Role(models.TextChoices):
        RESPONSIBLE = "responsible", "Responsible"
        ACCOUNTABLE = "accountable", "Accountable"
        CONSULTED = "consulted", "Consulted"
        INFORMED = "informed", "Informed"

    tenant_parent = "control"

    control = models.ForeignKey(Control, on_delete=models.CASCADE, related_name="responsibilities")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="responsibilities",
    )
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True,
        on_delete=models.CASCADE, related_name="responsibilities",
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="responsibilities_assigned",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["control", "role"]
        constraints = [
            models.UniqueConstraint(fields=["control", "user", "role"], name="uniq_resp_user_role"),
            models.UniqueConstraint(fields=["control", "vendor", "role"], name="uniq_resp_vendor_role"),
            models.CheckConstraint(
                condition=(models.Q(user__isnull=False, vendor__isnull=True)
                           | models.Q(user__isnull=True, vendor__isnull=False)),
                name="resp_exactly_one_party",
            ),
        ]
        verbose_name_plural = "responsibilities"

    def __str__(self):
        who = self.vendor or self.user
        return f"{self.control.control_id}: {who} is {self.get_role_display()}"
