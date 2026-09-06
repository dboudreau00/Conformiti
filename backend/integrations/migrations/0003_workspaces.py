"""0.9.0: every row belongs to a workspace. Existing rows join "Default"."""
import django.db.models.deletion
from django.db import migrations, models


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws, _ = Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})
    for name in MODELS:
        model = apps.get_model("integrations", name)
        model.objects.filter(workspace__isnull=True).update(workspace=ws)


MODELS = ['JiraIntegration', 'JiraBoard']


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_workspaces"),
        ("integrations", "0002_encrypt_secrets_at_rest"),
    ]

    operations = [
        migrations.AddField(model_name="jiraintegration", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="jiraboard", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
        migrations.AlterField(model_name="jiraintegration", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="jiraboard", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="jiraboard", name="board_id", field=models.PositiveIntegerField(help_text="Numeric board ID from Jira.")),
        migrations.AddConstraint(model_name="jiraboard", constraint=models.UniqueConstraint(fields=("workspace", "board_id"), name="uniq_board_per_workspace")),
    ]
