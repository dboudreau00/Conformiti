"""Record today's readiness snapshot (for cron deployments without Celery).

    0 6 * * *  cd /app/backend && ../.venv/bin/python manage.py record_readiness
"""
from django.core.management.base import BaseCommand

from analytics.snapshots import record_today


class Command(BaseCommand):
    help = "Record (or refresh) today's readiness snapshot for the dashboard trend."

    def handle(self, *args, **opts):
        snap = record_today(force=True)
        if snap is None:
            self.stderr.write("Snapshot not recorded (database error).")
            return
        self.stdout.write(self.style.SUCCESS(
            f"{snap.date}: {snap.implemented}/{snap.applicable} implemented ({snap.pct}%)"
        ))
