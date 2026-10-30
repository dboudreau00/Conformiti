"""Replace the package-signing key. The file holds the installation key; each workspace signs with a key derived
from it, so one rotation renews every workspace's key. SIGNING_KEY in the environment leaves no file to rotate."""
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts import tenancy
from accounts.models import Workspace
from attestations import signing


class Command(BaseCommand):
    help = "Rotate the Ed25519 key that signs sealed package manifests."

    def add_arguments(self, parser):
        parser.add_argument("--show", action="store_true", help="Only print the current keys.")
        parser.add_argument("--label", default="", help="A label for the new keys (e.g. 'FY27').")

    def _workspace_keys(self):
        """(workspace, key info) for every workspace, read with that workspace active: it selects the derived key."""
        out = []
        for workspace in Workspace.objects.order_by("pk"):
            with tenancy.scoped(workspace):
                out.append((workspace, signing.current_key_info(create=False)))
        return out

    def handle(self, *args, **options):
        # No workspace is active on a command line, which is how the installation key is read.
        with tenancy.unscoped():
            root = signing.current_key_info(create=True)
            if root.get("error"):
                raise CommandError(root["error"])
            if not root["enabled"]:
                raise CommandError("Signing is off (SIGNING_ENABLED=false).")
            if root["key_id"]:
                self.stdout.write(
                    f"Installation key : {root['key_id']}  sha256:{root['fingerprint']}  "
                    "(not published: each workspace signs with a key derived from it)")
            else:
                self.stdout.write("No signing key is configured (set SIGNING_KEY_FILE or SIGNING_KEY).")
            before = self._workspace_keys()
            for workspace, info in before:
                if info["key_id"]:
                    self.stdout.write(f"  {workspace.slug:<16} {info['key_id']}  sha256:{info['fingerprint']}")
            if options["show"]:
                return
            if getattr(settings, "SIGNING_KEY", ""):
                raise CommandError("SIGNING_KEY is set in the environment; rotate it there and restart.")
            location = (getattr(settings, "SIGNING_KEY_FILE", "") or "").strip()
            if not location:
                raise CommandError("SIGNING_KEY_FILE is not set; nothing to rotate.")
            path = Path(location)
            if path.exists() and root["key_id"]:
                retired = path.with_name(f"{path.name}.retired-{root['key_id']}")
                shutil.copy2(path, retired)
                os.chmod(retired, 0o600)
                path.unlink()
                self.stdout.write(f"Retired          : installation key {root['key_id']} (kept as {retired.name})")
            signing._cache.update(path=None, mtime=None, key=None)
            fresh = signing.current_key_info(create=True)
            if not fresh["key_id"]:
                raise CommandError("A new key could not be generated.")
            self.stdout.write(f"New installation : {fresh['key_id']}")

            # Registering retires only that workspace's previous key, so the published list stays right per tenant.
            for workspace in Workspace.objects.order_by("pk"):
                with tenancy.scoped(workspace):
                    info = signing.current_key_info(create=False)
                    if not info["key_id"]:
                        continue
                    row = signing.register_key(info["public_key"])
                    if options["label"]:
                        row.label = options["label"][:120]
                        row.save(update_fields=["label"])
                    self.stdout.write(self.style.SUCCESS(
                        f"New key {workspace.slug:<10}: {info['key_id']}  sha256:{info['fingerprint']}"))
        self.stdout.write("Publish each workspace's new fingerprint to its auditors; "
                          "packages sealed from now on carry it.")
