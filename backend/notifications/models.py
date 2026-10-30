from django.conf import settings
from django.db import models


class NotificationReceipt(models.Model):
    """Read and dismissed state per user and notification key; the notifications themselves are computed, not stored."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_receipts"
    )
    key = models.CharField(max_length=120)
    seen_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "key")
        indexes = [models.Index(fields=["user", "key"])]

    def __str__(self):
        return f"{self.user_id}:{self.key}"


class WebhookDelivery(models.Model):
    """One attempt to post an event to Slack or Teams, so an operator can see whether the channel is receiving."""
    event = models.CharField(max_length=40)
    channel = models.CharField(max_length=10)
    ok = models.BooleanField(default=False)
    response_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "webhook deliveries"

    def __str__(self):
        return f"{self.channel} {self.event} {'ok' if self.ok else 'failed'}"
