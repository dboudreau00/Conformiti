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


def point_codes_back_at_devices(apps, schema_editor):
    """Reverse: a code belongs to its owner's authenticator again.

    Before this migration a code could only exist under a TOTP device. An
    account with no device (a passkey-only person) has nowhere to put one, so
    its codes are removed, which is what the old schema could not have held.
    """
    MfaBackupCode = apps.get_model("accounts", "MfaBackupCode")
    MfaDevice = apps.get_model("accounts", "MfaDevice")
    devices = dict(MfaDevice.objects.values_list("user_id", "pk"))
    for code in MfaBackupCode.objects.all():
        device_id = devices.get(code.user_id)
        if device_id is None:
            code.delete()
        else:
            code.device_id = device_id
            code.save(update_fields=["device"])


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
        # Nullable first, with the data step that refills it on the way back:
        # reversing a bare RemoveField would re-add a NOT NULL column to a
        # table that has rows, which no database accepts.
        migrations.AlterField(
            model_name="mfabackupcode",
            name="device",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="backup_codes", to="accounts.mfadevice",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, point_codes_back_at_devices),
        migrations.RemoveField(
            model_name="mfabackupcode",
            name="device",
        ),
    ]
