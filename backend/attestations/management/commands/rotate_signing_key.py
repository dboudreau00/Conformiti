"""Replace the package-signing key.

    python manage.py rotate_signing_key            # new key into SIGNING_KEY_FILE
    python manage.py rotate_signing_key --show     # print the current key's fingerprint

The old key file is kept beside the new one as <file>.retired-<key id>, its
public key stays in the SigningKey table marked retired, and every package
already sealed keeps the public key that signed it -- so nothing in
circulation stops verifying. Packages sealed from now on use the new key.
With SIGNING_KEY set in the environment there is no file to rotate: change
the variable and restart.
"""
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from attestations import signing
from attestations.models import SigningKey


class Command(BaseCommand):
    help = "Rotate the Ed25519 key that signs sealed package manifests."

    def add_arguments(self, parser):
        parser.add_argument("--show", action="store_true", help="Only print the current key.")
        parser.add_argument("--label", default="", help="A label for the new key (e.g. 'FY27').")

    def handle(self, *args, **options):
        info = signing.current_key_info(create=True)
        if info.get("error"):
            raise CommandError(info["error"])
        if not info["enabled"]:
            raise CommandError("Signing is off (SIGNING_ENABLED=false).")
        if info["key_id"]:
            self.stdout.write(f"Current key : {info['key_id']}  sha256:{info['fingerprint']}")
        else:
            self.stdout.write("No signing key is configured (set SIGNING_KEY_FILE or SIGNING_KEY).")
        if options["show"]:
            return
        if getattr(settings, "SIGNING_KEY", ""):
            raise CommandError("SIGNING_KEY is set in the environment; rotate it there and restart.")
        location = (getattr(settings, "SIGNING_KEY_FILE", "") or "").strip()
        if not location:
            raise CommandError("SIGNING_KEY_FILE is not set; nothing to rotate.")
        path = Path(location)
        if path.exists() and info["key_id"]:
            retired = path.with_name(f"{path.name}.retired-{info['key_id']}")
            shutil.copy2(path, retired)
            os.chmod(retired, 0o600)
            SigningKey.objects.filter(key_id=info["key_id"], retired_at__isnull=True).update(
                retired_at=timezone.now())
            path.unlink()
            self.stdout.write(f"Retired     : {info['key_id']} (kept as {retired.name})")
        signing._cache.update(path=None, mtime=None, key=None)
        fresh = signing.current_key_info(create=True)
        if not fresh["key_id"]:
            raise CommandError("A new key could not be generated.")
        row = signing.register_key(fresh["public_key"])
        if options["label"]:
            row.label = options["label"][:120]
            row.save(update_fields=["label"])
        self.stdout.write(self.style.SUCCESS(
            f"New key     : {fresh['key_id']}  sha256:{fresh['fingerprint']}"))
        self.stdout.write("Publish the new fingerprint to your auditors; packages sealed from now on carry it.")
