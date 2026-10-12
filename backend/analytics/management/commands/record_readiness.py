"""Record today's readiness snapshot (for cron deployments without Celery).

    0 6 * * *  cd /app/backend && ../.venv/bin/python manage.py record_readiness

Every workspace in turn. A workspace that fails is named and does not stop the
others; the command exits with an error once they have run, so cron's mail says so.
"""
import logging

from django.core.management.base import BaseCommand, CommandError

from accounts import tenancy
from analytics.snapshots import record_today

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Record (or refresh) today's readiness snapshot for the dashboard trend, in every workspace."

    def handle(self, *args, **opts):
        failed = []
        for workspace in tenancy.for_each_workspace():
            try:
                snap = record_today(force=True)
            except Exception:
                logger.exception("Readiness snapshot failed for workspace %s", workspace.slug)
                snap = None
            if snap is None:
                failed.append(workspace.slug)
                self.stderr.write(f"{workspace.slug}: snapshot not recorded (see the log).")
                continue
            self.stdout.write(self.style.SUCCESS(
                f"{workspace.slug} {snap.date}: {snap.implemented}/{snap.applicable} implemented ({snap.pct}%)"
            ))
        if failed:
            raise CommandError(f"No snapshot was recorded for {', '.join(failed)}; the others were.")
