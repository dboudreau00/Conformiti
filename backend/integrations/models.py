"""Optional third-party integrations. Jira is the first: connection settings
live in the database so an administrator can configure them from the UI."""
from django.conf import settings
from django.db import models


class JiraIntegration(models.Model):
    """Single-row configuration for the Jira connection. The API token is
    stored in the application database and never returned by the API — use a
    scoped token created for this purpose, not a personal password."""
    base_url = models.URLField(blank=True, help_text="e.g. https://your-team.atlassian.net")
    email = models.EmailField(blank=True)
    api_token = models.CharField(max_length=255, blank=True)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Jira integration"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.base_url or "Jira (not configured)"


class JiraBoard(models.Model):
    """A Jira board this workspace tracks (e.g. the security backlog)."""
    board_id = models.PositiveIntegerField(unique=True, help_text="Numeric board ID from Jira.")
    name = models.CharField(max_length=160)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="jira_boards_added",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (#{self.board_id})"
