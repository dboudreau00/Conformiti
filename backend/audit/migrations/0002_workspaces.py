"""0.9.0: every row belongs to a workspace. Existing rows join "Default"."""
import django.db.models.deletion
from django.db import migrations, models


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws, _ = Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})
    for name in MODELS:
        model = apps.get_model("audit", name)
        model.objects.filter(workspace__isnull=True).update(workspace=ws)


MODELS = ['AuditLog']


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_workspaces"),
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.AddField(model_name="auditlog", name="workspace", field=models.ForeignKey(editable=False, blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
    ]
