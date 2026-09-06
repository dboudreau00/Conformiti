"""0.9.0: every row belongs to a workspace. Existing rows join "Default"."""
import django.db.models.deletion
from django.db import migrations, models


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws, _ = Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})
    for name in MODELS:
        model = apps.get_model("governance", name)
        model.objects.filter(workspace__isnull=True).update(workspace=ws)


MODELS = ['AccessReview', 'AccessReviewItem', 'MeetingSeries', 'MeetingMinute', 'ChampionGroup', 'GroupMember', 'Risk', 'RiskNote']


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_workspaces"),
        ("governance", "0002_vendors_and_responsibilities"),
    ]

    operations = [
        migrations.AddField(model_name="accessreview", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="accessreviewitem", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="meetingseries", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="meetingminute", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="championgroup", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="groupmember", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="risk", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="risknote", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
        migrations.AlterField(model_name="accessreview", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="accessreviewitem", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="meetingseries", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="meetingminute", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="championgroup", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="groupmember", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="risk", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="risknote", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="meetingseries", name="name", field=models.CharField(max_length=160)),
        migrations.AddConstraint(model_name="meetingseries", constraint=models.UniqueConstraint(fields=("workspace", "name"), name="uniq_series_name_per_workspace")),
        migrations.AlterField(model_name="championgroup", name="name", field=models.CharField(max_length=160)),
        migrations.AddConstraint(model_name="championgroup", constraint=models.UniqueConstraint(fields=("workspace", "name"), name="uniq_group_name_per_workspace")),
    ]
