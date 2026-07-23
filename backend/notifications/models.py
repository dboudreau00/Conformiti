"""Read / dismissed state for the derived per-user notifications."""
from django.conf import settings
from django.db import models


class NotificationReceipt(models.Model):
    """Tracks, per user and per stable notification key, whether an item has
    been seen (read) or dismissed. Notifications themselves are computed on the
    fly (see notifications.py); only this small state table is stored."""
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
