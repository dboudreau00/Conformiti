"""Encrypt the stored TOTP secret.

The column is widened first: an envelope for a 64-character base32 secret is
about 155 characters and would not fit the old varchar(64).

Reversible on purpose — reversing writes the plaintext secrets back into the
database, which is what "undo this migration" has to mean. Both directions skip
rows that are already in the target form, so a re-run after a partial failure
is safe.
"""
import config.fieldcrypto
from django.db import migrations

TABLE, COLUMN, AAD_COLUMN = "accounts_mfadevice", "secret", "user_id"


def encrypt_rows(apps, schema_editor):
    config.fieldcrypto.encrypt_existing_rows(
        schema_editor.connection, TABLE, COLUMN, AAD_COLUMN
    )


def decrypt_rows(apps, schema_editor):
    config.fieldcrypto.decrypt_existing_rows(
        schema_editor.connection, TABLE, COLUMN, AAD_COLUMN
    )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mfadevice',
            name='secret',
            field=config.fieldcrypto.EncryptedCharField(aad_from='user_id', max_length=255),
        ),
        migrations.RunPython(encrypt_rows, decrypt_rows),
    ]
