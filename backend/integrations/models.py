from django.conf import settings
from django.db import models

from config.fieldcrypto import EncryptedCharField

from accounts.tenancy import TenantModel


class JiraIntegration(TenantModel):
    base_url = models.URLField(blank=True, help_text="e.g. https://your-team.atlassian.net")
    email = models.EmailField(blank=True)
    # Encrypted at rest and bound to the row id, which get_solo() always sets explicitly;
    # max_length is the envelope width for a 255-byte token.
    api_token = EncryptedCharField(max_length=512, blank=True, aad_from="id")
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Jira integration"

    @classmethod
    def get_solo(cls):
        return cls.objects.order_by("pk").first() or cls.objects.create()

    def __str__(self):
        return self.base_url or "Jira (not configured)"


class JiraBoard(TenantModel):
    board_id = models.PositiveIntegerField(help_text="Numeric board ID from Jira.")
    name = models.CharField(max_length=160)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="jira_boards_added",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "board_id"], name="uniq_board_per_workspace"),
        ]

    def __str__(self):
        return f"{self.name} (#{self.board_id})"
