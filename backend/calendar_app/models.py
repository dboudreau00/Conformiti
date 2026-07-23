"""Calendar events shown on the dashboard (audits, tasks, custom milestones)."""
from django.conf import settings
from django.db import models


class CalendarEvent(models.Model):
    class Type(models.TextChoices):
        REVIEW_DUE = "review_due", "Document review due"
        AUDIT = "audit", "Audit / assessment"
        TASK = "task", "Task"
        CUSTOM = "custom", "Custom"

    title = models.CharField(max_length=255)
    event_type = models.CharField(max_length=20, choices=Type.choices, default=Type.CUSTOM)
    date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    all_day = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    document = models.ForeignKey(
        "documents.Document", null=True, blank=True,
        on_delete=models.CASCADE, related_name="calendar_events",
    )
    control = models.ForeignKey(
        "compliance.Control", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="calendar_events",
    )
    framework = models.ForeignKey(
        "compliance.Framework", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="calendar_events",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="calendar_events",
    )
    completed = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "title"]

    def __str__(self):
        return f"{self.date} - {self.title}"
