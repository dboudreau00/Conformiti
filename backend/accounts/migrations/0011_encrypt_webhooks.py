"""Encrypt the per-workspace Slack and Teams webhook URLs.

An incoming-webhook URL is a credential: whoever has it can post into the
channel as the app. 0.9.5 added these two columns as ordinary URLFields while
comparable secrets (the TOTP shared secret, the Jira API token) were already
encrypted, so a database dump handed them over in the clear.

The columns are widened first: the envelope for a 500-character URL is about
700 characters and would not fit the old varchar(500).

Reversible on purpose, like the TOTP migration: reversing writes the
plaintext URLs back, which is what "undo this migration" has to mean. Both
directions skip rows already in the target form, so a re-run after a partial
failure is safe.
"""
import config.fieldcrypto
from django.db import migrations

TABLE, AAD_COLUMN = "accounts_workspace", "id"
COLUMNS = ("slack_webhook_url", "teams_webhook_url")


def encrypt_rows(apps, schema_editor):
    for column in COLUMNS:
        config.fieldcrypto.encrypt_existing_rows(
            schema_editor.connection, TABLE, column, AAD_COLUMN
        )


def decrypt_rows(apps, schema_editor):
    for column in COLUMNS:
        config.fieldcrypto.decrypt_existing_rows(
            schema_editor.connection, TABLE, column, AAD_COLUMN
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_workspace_webhooks'),
    ]

    operations = [
        migrations.AlterField(
            model_name='workspace',
            name='slack_webhook_url',
            field=config.fieldcrypto.EncryptedCharField(
                aad_from='id', blank=True,
                help_text="This organisation's Slack incoming webhook. On an installation "
                          "with several organisations, tenant events are posted here or "
                          "nowhere.",
                max_length=800),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='teams_webhook_url',
            field=config.fieldcrypto.EncryptedCharField(
                aad_from='id', blank=True,
                help_text="This organisation's Teams incoming webhook.",
                max_length=800),
        ),
        migrations.RunPython(encrypt_rows, decrypt_rows),
    ]
