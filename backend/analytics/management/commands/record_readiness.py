"""Record today's readiness snapshot (for cron deployments without Celery).

    0 6 * * *  cd /app/backend && ../.venv/bin/python manage.py record_readiness
"""
from django.core.management.base import BaseCommand

from accounts import tenancy
from analytics.snapshots import record_today


class Command(BaseCommand):
    help = "Record (or refresh) today's readiness snapshot for the dashboard trend, in every workspace."

    def handle(self, *args, **opts):
        for workspace in tenancy.for_each_workspace():
            snap = record_today(force=True)
            if snap is None:
                self.stderr.write(f"{workspace.slug}: snapshot not recorded (database error).")
                continue
            self.stdout.write(self.style.SUCCESS(
                f"{workspace.slug} {snap.date}: {snap.implemented}/{snap.applicable} implemented ({snap.pct}%)"
            ))
