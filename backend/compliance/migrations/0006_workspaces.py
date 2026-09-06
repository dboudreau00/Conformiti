"""0.9.0: every row belongs to a workspace. Existing rows join "Default"."""
import django.db.models.deletion
from django.db import migrations, models


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws, _ = Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})
    for name in MODELS:
        model = apps.get_model("compliance", name)
        model.objects.filter(workspace__isnull=True).update(workspace=ws)


MODELS = ['Framework', 'ControlCategory', 'Control', 'ControlMapping', 'ControlEvidence', 'Responsibility']


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_workspaces"),
        ("compliance", "0005_vendors_and_responsibilities"),
    ]

    operations = [
        migrations.AddField(model_name="framework", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="controlcategory", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="control", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="controlmapping", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="controlevidence", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="responsibility", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
        migrations.AlterField(model_name="framework", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="controlcategory", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="control", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="controlmapping", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="controlevidence", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="responsibility", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="framework", name="key", field=models.SlugField(max_length=40)),
        migrations.AddConstraint(model_name="framework", constraint=models.UniqueConstraint(fields=("workspace", "key"), name="uniq_framework_key_per_workspace")),
    ]
