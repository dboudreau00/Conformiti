"""0.9.5oc review round, accounts: remove_demo_data, the admin's Workspace rules, bootstrap_demo on a second workspace,
the last-administrator race and the passkey counter."""
import os
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from testutils import make_doc, make_user

DEMO_PASSWORD = "DemoPass123!"
SEEDED = "demo-seeded"   # bootstrap_demo.SEEDED_OBJECT_TYPE; spelled out so this module also loads on older code


class RemoveDemoDataRealRowsTests(TestCase):
    """TEN-01 / ROB-01: a real row that shares a demo name, or has no creator, is not the demo's."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {"DEMO_PASSWORD": DEMO_PASSWORD})
        env.start()
        self.addCleanup(env.stop)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        media_root = override_settings(MEDIA_ROOT=media.name)
        media_root.enable()
        self.addCleanup(media_root.disable)
        call_command("seed_frameworks", "--with-folders", verbosity=0, stdout=StringIO())

    @staticmethod
    def remove(*args):
        out = StringIO()
        call_command("remove_demo_data", *args, stdout=out)
        return out.getvalue()

    @staticmethod
    def boot(*args):
        call_command("bootstrap_demo", *args, stdout=StringIO())

    @staticmethod
    def shapes():
        """The counts of every kind of row the command can delete."""
        from calendar_app.models import CalendarEvent
        from compliance.models import Responsibility
        from documents.models import Document, FolderPermission
        from governance.models import ChampionGroup, MeetingSeries, Risk
        from vendors.models import Vendor

        return {
            "raci": Responsibility.objects.count(), "series": MeetingSeries.objects.count(),
            "groups": ChampionGroup.objects.count(), "events": CalendarEvent.objects.count(),
            "risks": Risk.objects.count(), "vendors": Vendor.objects.count(),
            "documents": Document.objects.count(),
            "role_grants": FolderPermission.objects.filter(user__isnull=True).count(),
        }

    def real_rows_with_demo_shapes(self, real):
        """Rows a real install can hold that look like the demo's: names, no creator, the two role-wide grants."""
        from accounts.models import Role
        from calendar_app.models import CalendarEvent
        from compliance.models import Control, Responsibility
        from documents.models import EDIT, VIEW, Folder, FolderPermission
        from governance.models import ChampionGroup, MeetingSeries, Risk
        from vendors.models import Vendor

        control = Control.objects.first()
        viewer = make_user("someone")
        Responsibility.objects.create(control=control, user=viewer, role="responsible", created_by=real)
        Responsibility.objects.create(control=control, user=real, role="consulted", created_by=None)
        MeetingSeries.objects.create(name="Risk Review", owner=viewer, required_per_year=12)
        MeetingSeries.objects.create(name="Security Steering Committee", owner=None, required_per_year=4)
        ChampionGroup.objects.create(name="Security Champions", owner=None)
        CalendarEvent.objects.create(title="Quarterly access review", date=timezone.localdate(), created_by=None)
        Risk.objects.create(title="MFA not enforced for contractor accounts", created_by=real)
        Vendor.objects.create(name="Okta", created_by=None)
        Vendor.objects.create(name="Stripe", created_by=real)
        folder = Folder.objects.filter(control__isnull=False).first()
        make_doc(folder, None, name="Access Control Policy")
        cc6 = Folder.objects.filter(name__startswith="CC6 -").first()
        FolderPermission.objects.create(folder=cc6, role=Role.objects.get(name="Control Owner"), access_level=EDIT)
        iso = Folder.objects.filter(is_framework_root=True, name__icontains="27001").first()
        FolderPermission.objects.create(folder=iso, role=Role.objects.get(name="Auditor"), access_level=VIEW)

    def test_an_install_that_never_had_the_demo_loses_nothing_and_keeps_its_history(self):
        from analytics.models import ReadinessSnapshot
        from audit.models import AuditLog
        from documents.models import Document

        real = make_user("admin", superuser=True, email="admin@localhost")
        self.real_rows_with_demo_shapes(real)
        earlier = ReadinessSnapshot.objects.create(
            date=timezone.localdate() - timedelta(days=30), total_controls=217, applicable=217, implemented=3)
        stored = Document.objects.get(name="Access Control Policy").file.path
        before = self.shapes()

        first = self.remove()
        second = self.remove()

        self.assertEqual(self.shapes(), before)
        self.assertTrue(ReadinessSnapshot.objects.filter(pk=earlier.pk).exists())
        self.assertTrue(os.path.exists(stored), "the stored file of a real document must stay")
        self.assertIn("No sign that the demo dataset was loaded", first)
        self.assertIn("Seeded readiness history points deleted: 0", second)
        # The retirement is still recorded once, so SEED_DEMO_DATA=true cannot seed the demo into this install later.
        self.assertEqual(AuditLog.objects.filter(object_type="demo-data").count(), 1)

    def test_a_real_row_in_a_workspace_that_holds_the_demo_survives_its_retirement(self):
        from compliance.models import Responsibility
        from documents.models import EDIT, Folder, FolderPermission
        from governance.models import Risk
        from vendors.models import Vendor

        self.boot()
        make_user("realadmin", superuser=True)
        real = make_user("admin2", superuser=True, email="admin2@localhost")
        # The operator replaced the demo's Okta with their own, made a RACI row, and owns a risk of the same title.
        Vendor.objects.filter(name="Okta").delete()
        mine = Vendor.objects.create(name="Okta", created_by=real)
        orphan = Vendor.objects.create(name="Stripe-real")
        raci_real = Responsibility.objects.create(
            control=Responsibility.objects.first().control, user=real, role="informed", created_by=real)
        raci_orphan = Responsibility.objects.create(
            control=Responsibility.objects.first().control, user=real, role="consulted", created_by=None)
        Risk.objects.filter(title="MFA not enforced for contractor accounts").delete()
        risk = Risk.objects.create(title="MFA not enforced for contractor accounts", created_by=real)

        self.remove()

        self.assertTrue(Vendor.objects.filter(pk=mine.pk).exists())
        self.assertTrue(Vendor.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(Responsibility.objects.filter(pk=raci_real.pk).exists())
        self.assertTrue(Responsibility.objects.filter(pk=raci_orphan.pk).exists())
        self.assertTrue(Risk.objects.filter(pk=risk.pk).exists())
        # The demo's own rows are gone.
        self.assertFalse(Vendor.objects.filter(
            name__in=["Amazon Web Services", "Stripe", "Brightline Security Ltd"]).exists())
        self.assertFalse(Risk.objects.filter(title="Public-read ACL on legacy assets bucket").exists())
        cc6 = Folder.objects.filter(name__startswith="CC6 -")
        self.assertFalse(FolderPermission.objects.filter(user__isnull=True, access_level=EDIT, folder__in=cc6).exists())

    def test_a_grant_that_existed_before_the_demo_was_seeded_is_not_the_demos(self):
        from accounts.models import Role
        from documents.models import EDIT, Folder, FolderPermission

        cc6 = Folder.objects.filter(name__startswith="CC6 -").first()
        mine = FolderPermission.objects.create(folder=cc6, role=Role.objects.get(name="Control Owner"),
                                               access_level=EDIT)
        self.boot()
        make_user("realadmin", superuser=True)

        self.remove()

        self.assertTrue(FolderPermission.objects.filter(pk=mine.pk).exists())

    def test_a_second_run_leaves_what_was_made_after_the_retirement(self):
        from accounts.models import Role
        from analytics.models import ReadinessSnapshot
        from compliance.models import Control, Responsibility
        from documents.models import EDIT, Folder, FolderPermission
        from governance.models import MeetingSeries
        from vendors.models import Vendor

        self.boot()
        real = make_user("realadmin", superuser=True)
        self.remove()
        Vendor.objects.create(name="Okta", created_by=None)
        MeetingSeries.objects.create(name="Risk Review", owner=None, required_per_year=2)
        Responsibility.objects.create(control=Control.objects.first(), user=real, role="informed", created_by=None)
        FolderPermission.objects.create(folder=Folder.objects.filter(name__startswith="CC6 -").first(),
                                        role=Role.objects.get(name="Control Owner"), access_level=EDIT)
        trend = ReadinessSnapshot.objects.create(
            date=timezone.localdate() - timedelta(days=3), total_controls=217, applicable=217)
        before = self.shapes()

        out = self.remove()

        self.assertEqual(self.shapes(), before)
        self.assertTrue(ReadinessSnapshot.objects.filter(pk=trend.pk).exists())
        self.assertIn("Sample vendors deleted: 0", out)

    def test_a_demo_seeded_by_an_older_release_is_still_removed_with_its_orphans(self):
        """No record of the rows it made (the records are what this release adds), and its accounts deleted by hand."""
        from audit.models import AuditLog
        from vendors.models import Vendor
        from documents.models import Document

        self.boot()
        make_user("realadmin", superuser=True)
        AuditLog.objects.filter(object_type=SEEDED).delete()
        get_user_model().objects.filter(username__in=["admin", "mia", "owen", "aria", "val"]).delete()
        self.assertGreater(Vendor.objects.count(), 0)

        self.remove()

        self.assertEqual(Vendor.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(self.shapes()["raci"], 0)

    def test_a_demo_revived_with_force_is_retired_by_this_seeds_records(self):
        from vendors.models import Vendor

        self.boot()
        make_user("realadmin", superuser=True)
        self.remove()
        # Made while the demo was retired; the revival finds it by name, adopts it and does not record it.
        mine = Vendor.objects.create(name="Okta", created_by=None)
        self.boot("--force")
        self.assertTrue(Vendor.objects.filter(name="Stripe").exists())

        self.remove()

        self.assertFalse(Vendor.objects.filter(name="Stripe").exists())
        self.assertTrue(Vendor.objects.filter(pk=mine.pk).exists())

    def test_an_older_demo_refreshed_once_by_this_release_still_loses_its_role_grants(self):
        """The upgrade: the older release recorded nothing; the next boot records only the row it re-creates, which must
        not switch the older demo's own fallback off."""
        from audit.models import AuditLog
        from calendar_app.models import CalendarEvent
        from documents.models import Folder, FolderPermission

        self.boot()
        make_user("realadmin", superuser=True)
        AuditLog.objects.filter(object_type=SEEDED).delete()
        CalendarEvent.objects.filter(title="Quarterly access review").delete()
        self.boot()
        self.assertTrue(AuditLog.objects.filter(object_type=SEEDED, object_id="events").exists())

        self.remove()

        cc6 = Folder.objects.filter(name__startswith="CC6 -")
        iso = Folder.objects.filter(is_framework_root=True, name__icontains="27001")
        self.assertFalse(FolderPermission.objects.filter(
            user__isnull=True, role__name="Control Owner", folder__in=cc6).exists())
        self.assertFalse(FolderPermission.objects.filter(
            user__isnull=True, role__name="Auditor", folder__in=iso).exists())
        self.assertFalse(CalendarEvent.objects.filter(
            title__in=["SOC 2 Type II audit fieldwork", "ISO 27001 surveillance audit"]).exists())

    def test_a_real_vendor_with_a_demo_name_survives_a_demo_seeded_beside_it(self):
        """A real Okta makes the demo look present, but this boot makes every demo account, so the demo starts here and
        keeps records: only what it recorded is retired."""
        from vendors.models import Vendor

        mine = Vendor.objects.create(name="Okta", created_by=None)
        self.boot()
        make_user("realadmin", superuser=True)

        self.remove()

        self.assertTrue(Vendor.objects.filter(pk=mine.pk).exists())
        self.assertFalse(Vendor.objects.filter(name="Stripe").exists())


class WorkspaceSlugSigningKeyAdminTests(TestCase):
    """SEA-02 in the admin: a slug another workspace signed under is refused on the form, not by a server error."""

    def test_the_model_reports_a_slug_that_holds_a_signing_key_as_a_field_error(self):
        from django.core.exceptions import ValidationError

        from accounts.models import Workspace
        from attestations import signing

        with mock.patch.object(signing, "slug_reuses_a_registered_key", return_value=True):
            with self.assertRaises(ValidationError) as caught:
                Workspace(name="Taken Ltd", slug="taken").full_clean()
        self.assertIn("slug", caught.exception.message_dict)
        with mock.patch.object(signing, "slug_reuses_a_registered_key", return_value=False):
            Workspace(name="Free Ltd", slug="free").full_clean()


class WorkspaceAdminDefaultRulesTests(TestCase):
    """TEN-03: the Django admin saves through the model, so the model must hold the API's rules for Default."""

    def setUp(self):
        from accounts import tenancy

        self.default = tenancy.default_workspace()

    def test_the_model_refuses_to_archive_default_or_rename_its_slug(self):
        from django.core.exceptions import ValidationError

        self.default.is_active = False
        with self.assertRaises(ValidationError) as archived:
            self.default.full_clean()
        self.assertEqual(archived.exception.message_dict["is_active"], ["The Default workspace cannot be archived."])

        self.default.is_active = True
        self.default.slug = "renamed"
        with self.assertRaises(ValidationError) as renamed:
            self.default.full_clean()
        self.assertEqual(renamed.exception.message_dict["slug"], ["The Default workspace keeps its slug."])

    def test_other_workspaces_and_a_plain_edit_of_default_still_save(self):
        from accounts.models import Workspace

        self.default.name = "Head office"
        self.default.full_clean()
        other = Workspace.objects.create(name="Beta", slug="beta")
        other.is_active = False
        other.slug = "beta-2"
        other.full_clean()

    def test_the_admin_form_does_not_save_either_change(self):
        from django.test import Client

        root = make_user("root", superuser=True)
        client = Client()
        client.force_login(root)
        url = f"/admin/accounts/workspace/{self.default.pk}/change/"
        base = {"name": "Default", "slug": "default", "is_active": "on", "notification_email": "",
                "slack_webhook_url": "", "teams_webhook_url": ""}
        archive = {k: v for k, v in base.items() if k != "is_active"}
        for data in (archive, {**base, "slug": "renamed"}):
            response = client.post(url, data)
            self.assertEqual(response.status_code, 200, "the form is shown again with its error")
            self.default.refresh_from_db()
            self.assertTrue(self.default.is_active)
            self.assertEqual(self.default.slug, "default")


class BootstrapDemoSecondWorkspaceTests(TestCase):
    """TEN-05: the demo cannot be seeded where a username is already taken in another workspace, and a refusal leaves
    nothing behind."""

    DEMO_NAMES = ["admin", "mia", "owen", "aria", "val"]

    def setUp(self):
        from accounts.models import Workspace

        env = mock.patch.dict(os.environ, {"DEMO_PASSWORD": DEMO_PASSWORD})
        env.start()
        self.addCleanup(env.stop)
        self.second = Workspace.objects.create(name="Second", slug="second")

    def demo_names_present(self):
        from accounts import tenancy

        with tenancy.unscoped():
            return sorted(get_user_model().objects.filter(username__in=self.DEMO_NAMES)
                          .values_list("username", flat=True))

    @staticmethod
    def seed_second():
        call_command("bootstrap_demo", "--workspace", "second", stdout=StringIO())

    def test_a_first_name_taken_in_default_is_refused_with_a_message(self):
        from django.core.management import CommandError

        make_user("admin")   # the real administrator of Default
        with self.assertRaises(CommandError) as raised:
            self.seed_second()
        self.assertIn("admin", str(raised.exception))
        self.assertIn("another workspace", str(raised.exception))
        self.assertEqual(self.demo_names_present(), ["admin"])

    def test_a_later_name_taken_leaves_none_of_the_earlier_accounts_behind(self):
        from django.core.management import CommandError

        make_user("val")
        with self.assertRaises(CommandError):
            self.seed_second()
        self.assertEqual(self.demo_names_present(), ["val"])

    def test_a_platform_superuser_with_no_workspace_holds_the_name_too(self):
        from django.core.management import CommandError

        from accounts import tenancy

        root = make_user("admin", superuser=True)
        with tenancy.unscoped():
            get_user_model().objects.filter(pk=root.pk).update(workspace=None)
        with self.assertRaises(CommandError):
            self.seed_second()

    def test_a_failure_halfway_leaves_no_accounts(self):
        from accounts.management.commands.bootstrap_demo import Command

        with mock.patch.object(Command, "_permissions", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.seed_second()
        self.assertEqual(self.demo_names_present(), [])

    def test_a_workspace_holding_its_own_accounts_is_refreshed_as_before(self):
        self.seed_second()
        self.seed_second()
        self.assertEqual(self.demo_names_present(), sorted(self.DEMO_NAMES))


class LastAdministratorLockTests(TestCase):
    """TEN-06: the check that an administrator remains and the write that removes one run under a row lock. SQLite
    takes no row locks, so what is checked here is that the lock is asked for, on the users only, inside the request's
    own transaction, and that the guard still refuses."""

    def setUp(self):
        from testutils import make_roles

        self.roles = make_roles()
        self.boss = make_user("boss", self.roles["Administrator"])
        self.other = make_user("other", self.roles["Administrator"])

    def watch_locks(self):
        from django.db import connection
        from django.db.models.query import QuerySet

        seen = []
        original = QuerySet.select_for_update

        def record(queryset, *args, **kwargs):
            seen.append((queryset.model.__name__, kwargs, connection.in_atomic_block))
            return original(queryset, *args, **kwargs)

        patch = mock.patch.object(QuerySet, "select_for_update", record)
        patch.start()
        self.addCleanup(patch.stop)
        return seen

    @staticmethod
    def as_user(user):
        from rest_framework.test import APIClient

        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_demoting_an_administrator_locks_the_administrators_first(self):
        seen = self.watch_locks()
        r = self.as_user(self.boss).patch(f"/api/users/{self.other.pk}/", {"role": self.roles["Viewer"].pk},
                                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([(m, k) for m, k, _ in seen], [("User", {"of": ("self",)})])
        self.assertTrue(all(atomic for _, _, atomic in seen))

    def test_deactivating_and_deleting_one_lock_them_too(self):
        third = make_user("third", self.roles["Administrator"])
        seen = self.watch_locks()
        c = self.as_user(self.boss)
        self.assertEqual(c.patch(f"/api/users/{self.other.pk}/", {"is_active": False}, format="json").status_code, 200)
        self.assertEqual(c.delete(f"/api/users/{third.pk}/").status_code, 204)
        self.assertEqual(len(seen), 2)

    def test_changing_a_role_flag_locks_them_too(self):
        from accounts.models import Role

        custom = Role.objects.create(name="Custom admin", can_manage_users=True)
        make_user("custom", custom)
        seen = self.watch_locks()
        r = self.as_user(self.boss).patch(f"/api/roles/{custom.pk}/", {"can_manage_users": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(seen), 1)

    def test_an_edit_that_keeps_every_administrator_asks_for_no_lock(self):
        seen = self.watch_locks()
        r = self.as_user(self.boss).patch(f"/api/users/{self.other.pk}/", {"job_title": "x"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(seen, [])


class PasskeyCounterRaceTests(TestCase):
    """AUTH-04: two assertions that carry the same counter cannot both pass."""

    def test_the_second_of_two_assertions_with_one_counter_marks_the_key_suspect(self):
        from django.test import RequestFactory

        from accounts import passkeys, webauthn
        from accounts.models import WebAuthnCredential
        from accounts.tests_webauthn import FakeAuthenticator
        from testutils import make_roles

        user = make_user("owen", make_roles()["Control Owner"])
        authenticator = FakeAuthenticator()
        request = RequestFactory().post("/")
        begun = passkeys.begin_registration(user, request)
        passkeys.finish_registration(user, request, begun["state"], "Laptop", authenticator.create(begun["options"]))
        first = passkeys.begin_login(user, request)
        second = passkeys.begin_login(user, request)
        # Both copies of a cloned key increment once from the stored value.
        for_first = authenticator.get(first["options"], count=1)
        for_second = authenticator.get(second["options"], count=1)

        real = webauthn.counter_regressed
        interleaved = []

        def counter_regressed(stored, presented):
            # The other request lands between this one's read of the row and its write.
            if not interleaved:
                interleaved.append(True)
                passkeys.finish_login(user, request, {"state": second["state"], "credential": for_second})
            return real(stored, presented)

        with mock.patch.object(webauthn, "counter_regressed", counter_regressed):
            with self.assertRaises(passkeys.PasskeyRefused) as refused:
                passkeys.finish_login(user, request, {"state": first["state"], "credential": for_first})

        self.assertEqual(refused.exception.code, "clone")
        row = WebAuthnCredential.objects.get(user=user)
        self.assertIsNotNone(row.suspect_at)
        self.assertEqual(row.sign_count, 1)
