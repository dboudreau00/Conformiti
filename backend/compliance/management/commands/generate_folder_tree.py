"""
Write the physical compliance folder tree to disk, segregated by control.

    python manage.py generate_folder_tree
    python manage.py generate_folder_tree --root /path/to/output

The destination defaults to settings.COMPLIANCE_TREE_ROOT.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from compliance.folder_tree import build_tree


class Command(BaseCommand):
    help = "Generate the on-disk compliance folder tree (segregated by control)."

    def add_arguments(self, parser):
        parser.add_argument("--root", default=settings.COMPLIANCE_TREE_ROOT)
        parser.add_argument("--no-readmes", action="store_true",
                            help="Skip per-control _control.md metadata files.")

    def handle(self, *args, **opts):
        data_dir = os.path.join(settings.BASE_DIR, "compliance", "data")
        counts = build_tree(opts["root"], data_dir, write_readmes=not opts["no_readmes"])
        self.stdout.write(self.style.SUCCESS(
            f"Folder tree written to {opts['root']}\n"
            f"  frameworks={counts['frameworks']} categories={counts['categories']} "
            f"controls={counts['controls']} folders={counts['folders']}"
        ))
