"""Framework / control library models."""
from django.conf import settings
from django.db import models


class Framework(models.Model):
    """A compliance framework, e.g. SOC 2, ISO 27001, PCI DSS."""
    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=60, blank=True)
    authority = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} {self.version}".strip()


class ControlCategory(models.Model):
    """A grouping of controls within a framework (domain / requirement family)."""
    framework = models.ForeignKey(Framework, on_delete=models.CASCADE, related_name="categories")
    key = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["framework", "order", "key"]
        unique_together = ("framework", "key")

    def __str__(self):
        return self.name


class Control(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        IMPLEMENTED = "implemented", "Implemented"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    category = models.ForeignKey(ControlCategory, on_delete=models.CASCADE, related_name="controls")
    control_id = models.CharField(max_length=40)
    title = models.CharField(max_length=255)
    objective = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_controls",
    )

    # --- operating-effectiveness testing ---------------------------------
    # "Implemented" says the control was built; these say somebody checked it
    # still works, which is the question an auditor actually asks. Recorded
    # with who and when, because the audit middleware logs field NAMES only --
    # without provenance a single manager could backdate all 217 controls and
    # the trail would read `fields=last_tested_on` 217 times.
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
        ordering = ["category", "control_id"]
        unique_together = ("category", "control_id")

    @property
    def framework(self):
        return self.category.framework

    def __str__(self):
        return f"{self.control_id} - {self.title}"


class ControlMapping(models.Model):
    """
    Links controls across frameworks that address the same underlying theme,
    so a single piece of evidence can satisfy multiple standards.
    """
    theme = models.CharField(max_length=200)
    controls = models.ManyToManyField(Control, related_name="mappings")

    class Meta:
        ordering = ["theme"]

    def __str__(self):
        return self.theme


class ControlEvidence(models.Model):
    """
    Links a document (the evidence) to a control it helps satisfy.

    This is the reverse-mapping backbone: a control can cite many documents,
    and one document (e.g. an Access Control Policy) can satisfy controls
    across several frameworks at once. Each link records who made it and why,
    so the mapping itself is an audit artifact.
    """
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
