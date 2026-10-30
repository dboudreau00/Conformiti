"""Re-encrypt every encrypted column under the newest key in the ring. Run after putting the new key first in
DJANGO_FIELD_ENCRYPTION_KEY; drop the old key only once ``--status`` shows every row on the new one."""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from config import fieldcrypto


def encrypted_columns():
    """Every encrypted column, found through the model registry: a hand-written list would go stale and leave rows
    on the old key, unreadable once the old key is dropped."""
    found = []
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, fieldcrypto.EncryptedCharField):
                found.append((model, field))
    return sorted(found, key=lambda pair: (pair[0]._meta.db_table, pair[1].column))


class Command(BaseCommand):
    help = "Re-encrypt secrets under the newest field-encryption key."

    def add_arguments(self, parser):
        parser.add_argument("--status", action="store_true",
                            help="Report how many rows sit under each key, and change nothing.")

    def handle(self, *args, **opts):
        ids = fieldcrypto.key_ids()
        newest = ids[0]
        self.stdout.write(
            f"Key ring: {len(ids)} key(s), newest first: {', '.join(ids)}"
        )

        total_rotated = 0
        for model, field in encrypted_columns():
            attname = field.attname
            table, column = model._meta.db_table, field.column

            # Read the raw column, bypassing the decrypting descriptor.
            rows = list(model.objects.values_list("pk", attname))
            by_key = {}
            for _, raw in rows:
                # An empty value (a workspace with no webhook) holds no secret: neither plaintext nor on any key.
                bucket = ("empty" if raw in (None, "")
                          else fieldcrypto.envelope_key_id(raw) or "plaintext")
                by_key[bucket] = by_key.get(bucket, 0) + 1
            summary = ", ".join(f"{k}={n}" for k, n in sorted(by_key.items())) or "no rows"
            self.stdout.write(f"  {table}.{column}: {summary}")

            if opts["status"]:
                continue

            rotated = 0
            with transaction.atomic():
                for instance in model.objects.all():
                    # __dict__, not getattr: the decrypting descriptor would hide which key wrote the row.
                    raw = instance.__dict__.get(attname)
                    if raw in (None, "") or fieldcrypto.envelope_key_id(raw) == newest:
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
                            "current key, so it was left untouched."
                        ))
                        continue
                    # Assigning plaintext makes pre_save encrypt under the newest key.
                    setattr(instance, attname, plaintext)
                    instance.save(update_fields=[attname])
                    rotated += 1
            total_rotated += rotated
            self.stdout.write(f"    rotated {rotated} row(s) onto {newest}")

        if opts["status"]:
            self.stdout.write("Status only: nothing was changed.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Rotation complete: {total_rotated} row(s) now on key {newest}. "
                "Re-run with --status, and only then drop the old key."
            ))
