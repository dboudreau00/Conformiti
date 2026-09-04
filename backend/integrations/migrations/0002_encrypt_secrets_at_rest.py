"""Encrypt the stored Jira API token.

Same shape as accounts.0002: widen the column to hold the envelope, then
encrypt whatever is already there. Reversible, and idempotent in both
directions.
"""
import config.fieldcrypto
from django.db import migrations

TABLE, COLUMN, AAD_COLUMN = "integrations_jiraintegration", "api_token", "id"


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
        ('integrations', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jiraintegration',
            name='api_token',
            field=config.fieldcrypto.EncryptedCharField(blank=True, max_length=512),
        ),
        migrations.RunPython(encrypt_rows, decrypt_rows),
    ]
