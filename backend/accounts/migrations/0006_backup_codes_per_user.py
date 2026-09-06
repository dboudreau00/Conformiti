# Backup codes move from the TOTP device to the account, so a passkey-only
# person has a recovery factor too. Existing codes keep working: each row is
# re-pointed at the device's owner before the device column goes.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def point_codes_at_users(apps, schema_editor):
    MfaBackupCode = apps.get_model("accounts", "MfaBackupCode")
    for code in MfaBackupCode.objects.select_related("device").all():
        code.user_id = code.device.user_id
        code.save(update_fields=["user"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_passkeys"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="mfabackupcode",
            name="user",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="backup_codes", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(point_codes_at_users, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="mfabackupcode",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="backup_codes", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveField(
            model_name="mfabackupcode",
            name="device",
        ),
    ]
