"""Migration 0006 (backup codes move from the device to the account) runs both ways."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

APP = "accounts"
BEFORE = [(APP, "0005_passkeys")]
AFTER = [(APP, "0006_backup_codes_per_user")]


class BackupCodeMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Leave the schema at the latest migration for the tests that follow.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_forward_then_reverse_keeps_codes_with_a_device(self):
        old = self.migrate(BEFORE)
        Workspace = old.get_model(APP, "Workspace") if "Workspace" in {m.__name__ for m in old.get_models()} else None
        User = old.get_model(APP, "User")
        MfaDevice = old.get_model(APP, "MfaDevice")
        Code = old.get_model(APP, "MfaBackupCode")
        fields = {"username": "u1", "password": "x"}
        if Workspace is not None and any(f.name == "workspace" for f in User._meta.fields):
            fields["workspace"] = Workspace.objects.first() or Workspace.objects.create(name="D", slug="default")
        user = User.objects.create(**fields)
        device = MfaDevice.objects.create(user=user, secret="s")
        Code.objects.create(device=device, code_hash="h1")

        new = self.migrate(AFTER)
        NewCode = new.get_model(APP, "MfaBackupCode")
        self.assertEqual(NewCode.objects.get().user_id, user.pk)

        back = self.migrate(BEFORE)
        BackCode = back.get_model(APP, "MfaBackupCode")
        self.assertEqual(BackCode.objects.get().device_id, device.pk)
