"""Run the document review scan and send reminders (SES/SMTP).

Intended for cron when not running Celery beat, e.g. a daily crontab:
    0 8 * * *  cd /app && python manage.py send_review_reminders

Use --dry-run to see how many reminders would go out without sending them.
"""
from django.core.management.base import BaseCommand

from notifications.tasks import run_review_scan, run_vendor_scan


class Command(BaseCommand):
    help = ("Scan documents for upcoming/overdue reviews and vendors for lapsed SOC "
            "reports needing a bridge letter, and email the reminders.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be sent without emailing.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        count = run_review_scan(dry_run=dry)
        verb = "would be notified" if dry else "notified"
        self.stdout.write(self.style.SUCCESS(f"Review scan complete. Documents {verb}: {count}"))
        chased = run_vendor_scan(dry_run=dry)
        verb = "would be chased" if dry else "chased"
        self.stdout.write(self.style.SUCCESS(f"Vendor scan complete. Bridge letters {verb}: {chased}"))
