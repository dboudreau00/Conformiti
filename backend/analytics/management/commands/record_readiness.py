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
