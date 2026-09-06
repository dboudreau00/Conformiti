"""0.9.0: every row belongs to a workspace. Existing rows join "Default"."""
import django.db.models.deletion
from django.db import migrations, models


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws, _ = Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})
    for name in MODELS:
        model = apps.get_model("calendar_app", name)
        model.objects.filter(workspace__isnull=True).update(workspace=ws)


MODELS = ['CalendarEvent']


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_workspaces"),
        ("calendar_app", "0002_initial"),
    ]

    operations = [
        migrations.AddField(model_name="calendarevent", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
        migrations.AlterField(model_name="calendarevent", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
    ]
