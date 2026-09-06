"""Point-in-time readiness snapshots.

The dashboard's readiness trend needs history the live tables cannot give.
One row per day is recorded by the daily Celery task (and lazily by the
summary endpoint the first time it is hit on a given day), so the trend line
is real program history rather than an illustration.
"""
from django.db import models

from accounts.tenancy import TenantModel


class ReadinessSnapshot(TenantModel):
    date = models.DateField(db_index=True)
    total_controls = models.PositiveIntegerField(default=0)
    applicable = models.PositiveIntegerField(default=0)
    implemented = models.PositiveIntegerField(default=0)
    in_progress = models.PositiveIntegerField(default=0)
    with_evidence = models.PositiveIntegerField(default=0)
    evidence_links = models.PositiveIntegerField(default=0)
    documents_overdue = models.PositiveIntegerField(default=0)
    risks_open = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "date"], name="uniq_snapshot_date_per_workspace"),
        ]

    @property
    def pct(self):
        return round(self.implemented / self.applicable * 100) if self.applicable else 0

    def __str__(self):
        return f"{self.date}: {self.pct}%"
