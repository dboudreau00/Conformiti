"""Email each person who asked for a digest the items in their tray.

    python manage.py send_digests            # daily people today; weekly people on Mondays
    python manage.py send_digests --dry-run  # count only

Run daily from cron when Celery beat is not in use (the compose worker runs it
at REVIEW_SCAN_HOUR + 20 minutes).
"""
from django.core.management.base import BaseCommand

from notifications.tasks import run_digests


class Command(BaseCommand):
    help = "Send the emailed notification digests that are due today."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report without emailing.")

    def handle(self, *args, **options):
        n = run_digests(dry_run=options["dry_run"])
        verb = "would be sent" if options["dry_run"] else "sent"
        self.stdout.write(self.style.SUCCESS(f"Digests {verb}: {n}"))
