"""0.9.0: every row belongs to a workspace. Existing rows join "Default"."""
import django.db.models.deletion
from django.db import migrations, models


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws, _ = Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})
    for name in MODELS:
        model = apps.get_model("analytics", name)
        model.objects.filter(workspace__isnull=True).update(workspace=ws)


MODELS = ['ReadinessSnapshot']


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_workspaces"),
        ("analytics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(model_name="readinesssnapshot", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
        migrations.AlterField(model_name="readinesssnapshot", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="readinesssnapshot", name="date", field=models.DateField(db_index=True)),
        migrations.AddConstraint(model_name="readinesssnapshot", constraint=models.UniqueConstraint(fields=("workspace", "date"), name="uniq_snapshot_date_per_workspace")),
    ]
