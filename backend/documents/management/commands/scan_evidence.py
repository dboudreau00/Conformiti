"""Re-scan stored evidence through the malware scanner, and report on it.

    python manage.py scan_evidence --probe            # is clamd answering?
    python manage.py scan_evidence --stale 30         # files not scanned in 30 days (default)
    python manage.py scan_evidence --all              # every stored file
    python manage.py scan_evidence --all --dry-run    # count only

Exit code 1 when an infected file was found or the scanner is unreachable, so
a cron job can alert on it.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from documents import monitor
from documents.models import Document


class Command(BaseCommand):
    help = "Probe the malware scanner and re-scan stored evidence (quarantining what it flags)."

    def add_arguments(self, parser):
        parser.add_argument("--probe", action="store_true", help="Only check that clamd answers.")
        parser.add_argument("--all", action="store_true", help="Re-scan every stored document.")
        parser.add_argument("--stale", type=int, default=30,
                            help="Re-scan documents not scanned in this many days (default 30).")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many files.")
        parser.add_argument("--dry-run", action="store_true", help="Count what would be scanned.")

    def handle(self, *args, **options):
        if not monitor.enabled():
            self.stdout.write("Malware scanning is OFF (CLAMAV_ENABLED=false); nothing to do.")
            return
        state = monitor.probe(force=True)
        if not state["reachable"]:
            raise CommandError(f"The scanner is unreachable (down since {state['down_since']}).")
        self.stdout.write(self.style.SUCCESS(f"Scanner answered in {state['latency_ms']} ms."))
        if options["probe"]:
            return
        if options["all"]:
            qs = Document.objects.all()
        else:
            cutoff = timezone.now() - timezone.timedelta(days=max(0, options["stale"]))
            qs = Document.objects.filter(scanned_at__isnull=True) | Document.objects.filter(scanned_at__lt=cutoff)
        counts = monitor.rescan(qs, dry_run=options["dry_run"], limit=options["limit"] or None)
        verb = "would be scanned" if options["dry_run"] else "scanned"
        self.stdout.write(f"Documents {verb}: {counts['scanned']} "
                          f"(clean {counts['clean']}, infected {counts['infected']}, "
                          f"error {counts['error']}, no file {counts['skipped']})")
        held = monitor.quarantined().count()
        if held:
            self.stdout.write(self.style.WARNING(f"Quarantined documents now: {held}"))
        if counts["infected"]:
            raise CommandError(f"{counts['infected']} infected file(s) quarantined; see the audit log.")
