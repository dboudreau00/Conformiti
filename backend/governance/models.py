from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.tenancy import TenantModel


class AccessReview(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"

    name = models.CharField(max_length=160)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="access_reviews_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class AccessReviewItem(TenantModel):
    """One user's row in a review; the snapshot fields keep the evidence stable if the account changes later."""
    tenant_parent = "review"

    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        KEEP = "keep", "Keep access"
        MODIFY = "modify", "Modify access"
        REVOKE = "revoke", "Revoke access"

    review = models.ForeignKey(AccessReview, on_delete=models.CASCADE, related_name="items")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="access_review_items",
    )
    username = models.CharField(max_length=150)
    full_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    job_title = models.CharField(max_length=150, blank=True)
    role_name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    folder_grants = models.PositiveIntegerField(default=0)
    capabilities = models.CharField(max_length=200, blank=True)
    decision = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING)
    decision_notes = models.CharField(max_length=300, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="access_decisions_made",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return f"{self.review_id} · {self.username}"


class MeetingSeries(TenantModel):
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    required_per_year = models.PositiveSmallIntegerField(
        default=4, help_text="How many times per year this meeting must be held."
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="meeting_series_owned",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "meeting series"
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_series_name_per_workspace"),
        ]

    def __str__(self):
        return self.name


class MeetingMinute(TenantModel):
    tenant_parent = "series"

    series = models.ForeignKey(MeetingSeries, on_delete=models.CASCADE, related_name="minutes")
    date = models.DateField()
    title = models.CharField(max_length=200, blank=True)
    attendees = models.TextField(blank=True, help_text="Comma-separated names.")
    notes = models.TextField(blank=True)
    file = models.FileField(upload_to="meeting-minutes/", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="meeting_minutes_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.series.name}: {self.date}"


class ChampionGroup(TenantModel):
    name = models.CharField(max_length=160)
    purpose = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="champion_groups_owned",
        help_text="Accountable owner of this group.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_group_name_per_workspace"),
        ]

    def __str__(self):
        return self.name


class GroupMember(TenantModel):
    tenant_parent = "group"

    group = models.ForeignKey(ChampionGroup, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="champion_memberships"
    )
    department = models.CharField(max_length=120, help_text="The department this member champions.")
    note = models.CharField(max_length=200, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["department", "user__username"]
        unique_together = [("group", "user")]

    def __str__(self):
        return f"{self.group.name} · {self.user} ({self.department})"


class Risk(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        MITIGATING = "mitigating", "Mitigating"
        ACCEPTED = "accepted", "Accepted"
        CLOSED = "closed", "Closed"

    class Type(models.TextChoices):
        CONTROL_GAP = "control_gap", "Control gap"
        AUDIT_FINDING = "audit_finding", "Audit finding"
        PENTEST = "pentest", "Pen test"
        VENDOR = "vendor", "Vendor"
        INCIDENT = "incident", "Incident"
        OTHER = "other", "Other"

    class Treatment(models.TextChoices):
        MITIGATE = "mitigate", "Mitigate"
        ACCEPT = "accept", "Accept"
        TRANSFER = "transfer", "Transfer"
        AVOID = "avoid", "Avoid"

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    risk_type = models.CharField(max_length=20, choices=Type.choices, default=Type.OTHER)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    treatment = models.CharField(max_length=10, choices=Treatment.choices, default=Treatment.MITIGATE)
    likelihood = models.PositiveSmallIntegerField(default=3)  # 1-5
    impact = models.PositiveSmallIntegerField(default=3)      # 1-5
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_risks",
    )
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="risks",
    )
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="risks",
    )
    due_date = models.DateField(null=True, blank=True)
    identified_on = models.DateField(default=timezone.localdate)
    jira_key = models.CharField(max_length=40, blank=True)
    mitigation_plan = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_risks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def score(self):
        return self.likelihood * self.impact

    @property
    def rating(self):
        s = self.score
        if s >= 16:
            return "critical"
        if s >= 10:
            return "high"
        if s >= 5:
            return "moderate"
        return "low"

    @property
    def is_overdue(self):
        return bool(
            self.due_date
            and self.due_date < timezone.localdate()
            and self.status in (self.Status.OPEN, self.Status.MITIGATING)
        )


class RiskNote(TenantModel):
    tenant_parent = "risk"
    risk = models.ForeignKey(Risk, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="risk_notes",
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Note on {self.risk_id} by {self.author_id}"
