"""Give the old fallback administrator an address the demo tests do not match.

Before 0.9.5l the entrypoint made the account named by DJANGO_SUPERUSER_USERNAME
with the address ``admin@example.com`` when DJANGO_SUPERUSER_EMAIL was unset,
and it made it with no workspace. Migration 0013 attached those accounts to a
workspace, which is where the demo checks look: a superuser ``admin`` whose
address ends in ``@example.com`` is taken for the demo administrator. The boot
banner then told the operator to run ``remove_demo_data``, which deactivates
that account, takes the owner off its controls and deletes the readiness
history from before today.

The demo accounts the seeder makes all have a name, and only its administrator
(Ada Admin) is a superuser. The account this repairs was made by
``createsuperuser`` and has no name, so it is the superuser with a demo
account's username, in practice ``admin``, and both name fields blank. It gets
the address ``createsuperuser`` now falls back to, ``admin@localhost``.
Accounts with a name, any other address or any other username are left alone,
and so is an installation with none of them: safe on any database and
idempotent. The reverse is a no-op, because putting the demo address back
would recreate the hazard.
"""
from django.db import migrations

OLD_FALLBACK = "admin@example.com"
NEW_FALLBACK = "admin@localhost"
# The seeder's usernames, copied so this migration means the same thing
# whatever the seeder later does.
DEMO_USERNAMES = ("admin", "mia", "owen", "aria", "val")


def rewrite(apps, schema_editor):
    db = schema_editor.connection.alias
    User = apps.get_model("accounts", "User")
    # The base manager, as in 0013: it never adds a workspace filter.
    User._base_manager.using(db).filter(
        is_superuser=True, username__in=DEMO_USERNAMES, email__iexact=OLD_FALLBACK,
        first_name="", last_name="",
    ).update(email=NEW_FALLBACK)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_attach_workspaceless_superusers"),
    ]

    operations = [
        migrations.RunPython(rewrite, migrations.RunPython.noop),
    ]
