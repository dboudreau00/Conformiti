"""0.9.0: workspaces. Creates the model and the "Default" workspace every
existing row joins, attaches people and roles to it, and makes role names
unique per workspace rather than per installation."""
import django.db.models.deletion
from django.db import migrations, models

import accounts.tenancy


def create_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    Workspace.objects.get_or_create(slug="default", defaults={"name": "Default"})


def assign_default(apps, schema_editor):
    Workspace = apps.get_model("accounts", "Workspace")
    ws = Workspace.objects.get(slug="default")
    for name in ("Role", "User"):
        apps.get_model("accounts", name).objects.filter(workspace__isnull=True).update(workspace=ws)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_digest_preference"),
    ]

    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=60, unique=True)),
                ("is_active", models.BooleanField(default=True, help_text="Archived workspaces refuse sign-in and drop out of every job.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.RunPython(create_default, migrations.RunPython.noop),
        migrations.AddField(model_name="role", name="workspace", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AddField(model_name="user", name="workspace", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="users", to="accounts.workspace")),
        migrations.RunPython(assign_default, migrations.RunPython.noop),
        migrations.AlterField(model_name="role", name="workspace", field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="accounts.workspace")),
        migrations.AlterField(model_name="role", name="name", field=models.CharField(max_length=80)),
        migrations.AddConstraint(model_name="role", constraint=models.UniqueConstraint(fields=("workspace", "name"), name="uniq_role_name_per_workspace")),
        migrations.AlterModelManagers(name="user", managers=[("objects", accounts.tenancy.TenantUserManager())]),
    ]
