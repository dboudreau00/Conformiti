"""Replace the package-signing key.

    python manage.py rotate_signing_key            # new key into SIGNING_KEY_FILE
    python manage.py rotate_signing_key --show     # print the current keys

The file holds the installation key. A package is signed with a key derived
from it for the package's own workspace, so one rotation gives every workspace a
new key, and the fingerprints to publish are the workspaces', not the file's.

The old key file is kept beside the new one as <file>.retired-<key id>, each
workspace's old public key stays in the SigningKey table marked retired, and
every package already sealed keeps the public key that signed it, so nothing in
circulation stops verifying. Packages sealed from now on use the new keys.
With SIGNING_KEY set in the environment there is no file to rotate: change
the variable and restart.
"""
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
        """(workspace, key info) for every workspace, each read with that
        workspace active, because that is the key its packages are signed with."""
        out = []
        for workspace in Workspace.objects.order_by("pk"):
            with tenancy.scoped(workspace):
                out.append((workspace, signing.current_key_info(create=False)))
        return out

    def handle(self, *args, **options):
        # A command line has no workspace active, which is how the installation
        # key is read; the workspaces are visited one at a time below.
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

            # Each workspace's derived key is new now. Registering it retires that
            # workspace's previous current key and leaves every other workspace's
            # alone, so the published list stays right per organisation.
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
