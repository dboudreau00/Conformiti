"""bootstrap_demo and remove_demo_data across container boots.

The Docker entrypoint runs bootstrap_demo on every boot while SEED_DEMO_DATA
is true, and a container keeps that variable for life (restart:
unless-stopped reruns it on every host reboot). Once remove_demo_data has
retired the demo, those later boots must leave the workspace alone: no
sample records back among the real ones, and no demo accounts recreated.
"""
import os
import re
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from accounts import tenancy
from accounts.management.commands.bootstrap_demo import RETIRED_OBJECT_TYPE, retired
from accounts.models import Workspace
from testutils import make_user

DEMO_PASSWORD = "DemoPass123!"
DEMO_USERNAMES = ["admin", "mia", "owen", "aria", "val"]


class DemoRetirementTests(TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"DEMO_PASSWORD": DEMO_PASSWORD})
        env.start()
        self.addCleanup(env.stop)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        media_root = override_settings(MEDIA_ROOT=media.name)
        media_root.enable()
        self.addCleanup(media_root.disable)

        call_command("seed_frameworks", "--with-folders", verbosity=0)
        self.boot()
        # remove_demo_data refuses to leave the workspace without an
        # administrator of its own.
        make_user("realadmin", superuser=True)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def boot(*args):
        """What the entrypoint's SEED_DEMO_DATA=true branch runs."""
        out = StringIO()
        call_command("bootstrap_demo", *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def remove(*args):
        out = StringIO()
        call_command("remove_demo_data", *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def sample_counts():
        from calendar_app.models import CalendarEvent
        from documents.models import Document
        from governance.models import Risk
        from vendors.models import Vendor

        return {"documents": Document.objects.count(), "risks": Risk.objects.count(),
                "vendors": Vendor.objects.count(), "events": CalendarEvent.objects.count()}

    @staticmethod
    def demo_accounts():
        return get_user_model().objects.filter(username__in=DEMO_USERNAMES)

    def assert_nothing_seeded(self):
        self.assertEqual(self.sample_counts(),
                         {"documents": 0, "risks": 0, "vendors": 0, "events": 0})

    # -- the defect: a later boot re-seeding a retired workspace --------------
    def test_a_later_boot_does_not_seed_the_demo_back(self):
        self.remove()
        self.assert_nothing_seeded()

        out = self.boot()
        self.boot()  # and the boot after that

        self.assertIn("not seeded", out)
        self.assert_nothing_seeded()
        self.assertFalse(self.demo_accounts().filter(is_active=True).exists())
        from config.health import demo_accounts_present
        self.assertFalse(demo_accounts_present(),
                         "the boot banner and /api/health/ read this; it must stay off")

    def test_a_later_boot_does_not_recreate_deleted_accounts(self):
        self.remove("--delete")
        self.assertFalse(self.demo_accounts().exists())

        out = self.boot()

        self.assertNotIn("Sign in as", out, "no new demo password may be issued")
        self.assertFalse(self.demo_accounts().exists())
        self.assert_nothing_seeded()

    def test_the_retirement_is_recorded_once_and_survives_a_second_run(self):
        from audit.models import AuditLog

        self.remove()
        self.remove()  # idempotent; its seeded-row cleanup must not take the record
        self.assertEqual(AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE).count(), 1)
        self.assertTrue(retired())

    def test_a_dry_run_retires_nothing(self):
        from audit.models import AuditLog

        before = self.sample_counts()
        self.remove("--dry-run")

        self.assertFalse(AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE).exists())
        self.assertFalse(retired())
        out = self.boot()
        self.assertIn("refreshed", out)
        self.assertEqual(self.sample_counts(), before)

    def test_accounts_switched_off_before_the_record_existed_count_as_retired(self):
        """A workspace retired by a release older than the record: the demo
        accounts are there, and none of them can sign in."""
        from audit.models import AuditLog

        self.remove()
        AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE).delete()
        self.assertTrue(self.demo_accounts().exists())

        self.assertTrue(retired())
        self.boot()
        self.assert_nothing_seeded()

    def test_force_seeds_again_and_makes_the_accounts_usable(self):
        self.remove()

        out = self.boot("--force")

        self.assertIn("Sign in as  admin", out)
        self.assertEqual(self.sample_counts()["documents"], 9)
        admin = self.demo_accounts().get(username="admin")
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.check_password(DEMO_PASSWORD))
        self.assertEqual(self.demo_accounts().filter(is_active=True).count(), 5)

    def test_after_force_later_boots_refresh_the_demo_instead_of_calling_it_removed(self):
        """--force used to leave the retirement standing: every later boot
        said the demo 'stays removed' while the banner said its accounts were
        live, and the refresh never ran again."""
        from audit.models import AuditLog

        self.remove()
        self.boot("--force")

        self.assertFalse(retired())
        out = self.boot()
        self.assertNotIn("not seeded", out)
        self.assertIn("refreshed", out)
        # The trail is immutable: the retirement stays, and the revival
        # follows it.
        markers = list(AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE)
                       .order_by("pk").values_list("action", flat=True))
        self.assertEqual(markers, ["delete", "create"])

        # Retiring it again is recorded again, and holds.
        self.remove()
        self.remove()
        self.assertTrue(retired())
        self.assertIn("not seeded", self.boot())
        self.assert_nothing_seeded()
        markers = list(AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE)
                       .order_by("pk").values_list("action", flat=True))
        self.assertEqual(markers, ["delete", "create", "delete"])

    def test_the_retirement_belongs_to_one_workspace(self):
        self.remove()
        other = Workspace.objects.create(name="Beta Ltd", slug="beta-demo")
        with tenancy.scoped(other):
            self.assertFalse(retired())
        self.assertTrue(retired())

    # -- the wording ------------------------------------------------------------
    def test_no_output_calls_the_demo_password_published(self):
        """The password is generated per installation and printed once; a
        'published' password reads as a well-known credential."""
        out = self.remove()
        self.assertIn("Demo data removed.", out)
        self.assertNotIn("published", out)
        self.assertNotIn("published", self.boot())


class EntrypointDemoBannerTests(SimpleTestCase):
    """What backend/entrypoint.sh says about the demo at every boot."""

    source = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(encoding="utf-8")

    def test_the_banner_reports_the_database_not_the_variable(self):
        """SEED_DEMO_DATA stays set after remove_demo_data; the banner has to
        agree with /api/health/, which asks the database."""
        self.assertIn("demo_accounts_present()", self.source)

    def test_no_line_calls_the_demo_password_published(self):
        self.assertNotIn("published", self.source)

    def test_the_header_states_the_default_the_code_uses(self):
        default = re.search(r'case "\$\{SEED_DEMO_DATA:-(\w+)\}"', self.source).group(1)
        self.assertIn(f"SEED_DEMO_DATA, default {default}", self.source)
