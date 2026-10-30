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
    # Mean applicable-control score (0-100) that day; null on rows recorded before scores were stored.
    score = models.PositiveSmallIntegerField(null=True, blank=True)
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
