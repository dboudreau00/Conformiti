from django.conf import settings
from django.db import models

from accounts.tenancy import TenantModel


class AuditLog(TenantModel):
    # The workspace the action happened in, which is the active one and not the actor's own.
    # No-workspace paths (sign-in, SSO) pass it explicitly; null covers a failed sign-in for an unknown username.
    workspace = models.ForeignKey(
        "accounts.Workspace", null=True, blank=True, on_delete=models.CASCADE,
        related_name="+", editable=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_entries",
    )
    action = models.CharField(max_length=20)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=80, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        who = self.user or "system"
        return f"{self.timestamp:%Y-%m-%d %H:%M} {who} {self.action} {self.object_type}"
