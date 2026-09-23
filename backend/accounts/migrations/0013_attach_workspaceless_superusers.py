"""Attach superusers that belong to no workspace to the one they already land in.

Before this release ``createsuperuser`` ran with no workspace active, so the
account it made belonged to none. That account could sign in to /admin/ and
was shown the sign-in form again, and with that admin session in the same
browser the web app refused it too: a request's user lookup is pinned to the
workspace the request resolves to, which a row with no workspace never
matches. ``createsuperuser`` now files the account itself (see
accounts/tenancy.py); this moves the ones made earlier to where such an
account already landed on every request: the first workspace that is not
archived, else Default.

Idempotent and safe on any database: only superusers with no workspace are
touched, and when there are none nothing is read further and no workspace is
created. The reverse is a no-op, since which accounts had no workspace is not
recorded anywhere.
"""
from django.db import migrations


def attach(apps, schema_editor):
    db = schema_editor.connection.alias
    User = apps.get_model("accounts", "User")
    Workspace = apps.get_model("accounts", "Workspace")
    # The base manager, not the tenant one: it never adds a workspace filter,
    # whatever happens to be active around the migration.
    orphans = User._base_manager.using(db).filter(workspace__isnull=True, is_superuser=True)
    if not orphans.exists():
        return
    target = Workspace.objects.using(db).filter(is_active=True).order_by("pk").first()
    if target is None:
        target, _ = Workspace.objects.using(db).get_or_create(
            slug="default", defaults={"name": "Default"})
    orphans.update(workspace=target)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_user_sessions_valid_from"),
    ]

    operations = [
        migrations.RunPython(attach, migrations.RunPython.noop),
    ]
