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
