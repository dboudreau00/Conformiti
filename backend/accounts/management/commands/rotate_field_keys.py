"""
Re-encrypt every encrypted column under the newest key in the ring.

    python manage.py rotate_field_keys --status   # report only, changes nothing
    python manage.py rotate_field_keys            # rewrite rows under the newest key

Rotating a key is a three-step operation and this command is the middle one:

  1. Put the new key at the FRONT of DJANGO_FIELD_ENCRYPTION_KEY (or the first
     line of the key file), keeping the old one after it. Both keys decrypt;
     the first encrypts. Restart. Nothing breaks -- existing rows are still
     readable under the old key.
  2. Run this command. Every row is read under whichever key wrote it and
     written back under the newest one.
  3. Once `--status` reports every row on the new key, drop the old key and
     restart.

Doing step 3 before step 2 is what makes secrets unreadable, which is why
`--status` reports per key rather than just a total.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from config import fieldcrypto

# (model label, attribute). Extend this when a column becomes encrypted --
# a column missing here is silently never rotated.
ENCRYPTED_COLUMNS = [
    ("accounts.MfaDevice", "secret"),
    ("integrations.JiraIntegration", "api_token"),
]


class Command(BaseCommand):
    help = "Re-encrypt secrets under the newest field-encryption key."

    def add_arguments(self, parser):
        parser.add_argument("--status", action="store_true",
                            help="Report how many rows sit under each key, and change nothing.")

    def handle(self, *args, **opts):
        from django.apps import apps

        ids = fieldcrypto.key_ids()
        newest = ids[0]
        self.stdout.write(
            f"Key ring: {len(ids)} key(s), newest first: {', '.join(ids)}"
        )

        total_rotated = 0
        for label, attname in ENCRYPTED_COLUMNS:
            model = apps.get_model(label)
            field = model._meta.get_field(attname)
            table, column = model._meta.db_table, field.column

            # Read the raw column, bypassing the decrypting descriptor.
            rows = list(model.objects.values_list("pk", attname))
            by_key = {}
            for _, raw in rows:
                by_key[fieldcrypto.envelope_key_id(raw) or "plaintext"] = \
                    by_key.get(fieldcrypto.envelope_key_id(raw) or "plaintext", 0) + 1
            summary = ", ".join(f"{k}={n}" for k, n in sorted(by_key.items())) or "no rows"
            self.stdout.write(f"  {table}.{column}: {summary}")

            if opts["status"]:
                continue

            rotated = 0
            with transaction.atomic():
                for instance in model.objects.all():
                    # Read __dict__ directly: getattr would go through the
                    # decrypting descriptor and we need to see which key wrote
                    # the row before deciding whether to touch it.
                    raw = instance.__dict__.get(attname)
                    if fieldcrypto.envelope_key_id(raw) == newest:
                        continue
                    plaintext = raw
                    if fieldcrypto.is_encrypted(raw):
                        plaintext = fieldcrypto.decrypt(
                            raw, field.aad_for_instance(instance)
                        )
                    if plaintext in (None, ""):
                        # Unreadable under every key in the ring: leave it alone
                        # rather than replacing a recoverable ciphertext with "".
                        self.stderr.write(self.style.WARNING(
                            f"    {table}#{instance.pk}.{column} is not readable under any "
                            "current key -- left untouched."
                        ))
                        continue
                    # Assigning plaintext makes pre_save encrypt under the newest key.
                    setattr(instance, attname, plaintext)
                    instance.save(update_fields=[attname])
                    rotated += 1
            total_rotated += rotated
            self.stdout.write(f"    rotated {rotated} row(s) onto {newest}")

        if opts["status"]:
            self.stdout.write("Status only -- nothing was changed.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Rotation complete: {total_rotated} row(s) now on key {newest}. "
                "Re-run with --status, and only then drop the old key."
            ))
