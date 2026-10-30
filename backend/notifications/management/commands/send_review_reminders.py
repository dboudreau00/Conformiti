from django.core.management.base import BaseCommand, CommandError

from accounts.models import Workspace
from notifications.tasks import run_all_scans


class Command(BaseCommand):
    help = ("Scan documents for upcoming/overdue reviews, vendors for lapsed SOC "
            "reports needing a bridge letter, and auditor (PBC) requests falling due, "
            "and email the reminders.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be sent without emailing.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        results = run_all_scans(dry_run=dry)
        names = dict(Workspace.objects.values_list("slug", "name"))
        failed = []
        for slug, counts in results.items():
            self.stdout.write(f"Workspace: {names.get(slug, slug)} ({slug})")
            if counts is None:
                failed.append(slug)
                self.stderr.write(f"  The morning scan failed for {slug}; see the log for why.")
                continue
            verb = "would be notified" if dry else "notified"
            self.stdout.write(self.style.SUCCESS(
                f"  Review scan complete. Documents {verb}: {counts['documents']}"))
            verb = "would be chased" if dry else "chased"
            self.stdout.write(self.style.SUCCESS(
                f"  Vendor scan complete. Bridge letters {verb}: {counts['vendors']}"))
            verb = "would be reminded" if dry else "reminded"
            self.stdout.write(self.style.SUCCESS(
                f"  PBC scan complete. Auditor requests {verb}: {counts['pbc']}"))
        if failed:
            raise CommandError(
                f"The morning scan failed for {', '.join(failed)}; the other workspaces ran.")
