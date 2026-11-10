"""Re-scans stored evidence. Exits non-zero when a file is infected or the scanner is unreachable, so cron can alert."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from documents import monitor
from documents.models import Document, DocumentVersion, FormTemplate


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
        cutoff = timezone.now() - timezone.timedelta(days=max(0, options["stale"]))
        counts = {"scanned": 0, "clean": 0, "infected": 0, "error": 0, "skipped": 0}
        left = options["limit"] or None
        # Archived versions and form templates are files the product serves too, so the sweep opens them as well.
        for model in (Document, DocumentVersion, FormTemplate):
            if left is not None and left <= 0:
                break
            if options["all"]:
                qs = model.objects.all()
            else:
                qs = model.objects.filter(scanned_at__isnull=True) | model.objects.filter(scanned_at__lt=cutoff)
            part = monitor.rescan(qs, dry_run=options["dry_run"], limit=left)
            for key, value in part.items():
                counts[key] += value
            if left is not None:
                left -= part["scanned"] + part["skipped"]
        verb = "would be scanned" if options["dry_run"] else "scanned"
        self.stdout.write(f"Files {verb}: {counts['scanned']} "
                          f"(clean {counts['clean']}, infected {counts['infected']}, "
                          f"error {counts['error']}, no file {counts['skipped']})")
        held = (monitor.quarantined().count()
                + DocumentVersion.objects.filter(quarantined_at__isnull=False).count()
                + FormTemplate.objects.filter(quarantined_at__isnull=False).count())
        if held:
            self.stdout.write(self.style.WARNING(f"Quarantined files now: {held}"))
        if counts["infected"]:
            raise CommandError(f"{counts['infected']} infected file{'' if counts['infected'] == 1 else 's'} quarantined; "
                               "see the audit log.")
