"""bootstrap_demo and remove_demo_data across container boots.

The Docker entrypoint runs bootstrap_demo on every boot while SEED_DEMO_DATA
is true, and a container keeps that variable for life (restart:
unless-stopped reruns it on every host reboot). Once remove_demo_data has
retired the demo, those later boots must leave the workspace alone: no
sample records back among the real ones, and no demo accounts recreated.
"""
import contextlib
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

        call_command("seed_frameworks", "--with-folders", verbosity=0, stdout=StringIO())
        self.first_boot = self.boot()
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
    def test_the_seed_names_createsuperuser_first_until_an_own_administrator_exists(self):
        """remove_demo_data refuses while the demo accounts are the only
        administrators, so advice naming it alone failed exactly as printed."""
        out = self.first_boot  # before setUp made realadmin
        self.assertIn("manage.py createsuperuser", out)
        self.assertLess(out.index("manage.py createsuperuser"), out.index("manage.py remove_demo_data"))

        # With an administrator of the operator's own, it is the one command.
        self.remove()
        out = self.boot("--force")
        self.assertIn("Sign in as  admin", out)
        self.assertIn("manage.py remove_demo_data", out)
        self.assertNotIn("createsuperuser", out)

    def test_no_output_calls_the_demo_password_published(self):
        """The password is generated per installation and printed once; a
        'published' password reads as a well-known credential."""
        out = self.remove()
        self.assertIn("Demo data removed.", out)
        self.assertNotIn("published", out)
        self.assertNotIn("published", self.boot())

    def test_a_real_run_reports_what_it_did_and_a_dry_run_what_it_would_do(self):
        """A real run used to list every deletion as 'will be deleted' after
        making it, then one line in the past tense; the history count was
        missing from a dry run."""
        dry = self.remove("--dry-run")
        self.assertRegex(dry, r"Demo users that would be deactivated: .*\badmin\b")
        self.assertIn("Sample documents that would be deleted: 9", dry)
        self.assertIn("Seeded readiness history points that would be deleted: 5", dry)
        self.assertNotIn("will", dry)

        out = self.remove()
        self.assertRegex(out, r"Demo users deactivated: .*\badmin\b")
        self.assertIn("Sample documents deleted: 9", out)
        self.assertIn("Seeded readiness history points deleted: 5", out)
        self.assertNotIn("will be", out)
        self.assertNotIn("would", out)

    # -- the demo's control programme ------------------------------------------
    @staticmethod
    def statuses():
        from collections import Counter

        from compliance.models import Control

        return dict(Counter(Control.objects.values_list("status", flat=True)))

    @staticmethod
    def demo_owned():
        from compliance.models import Control

        return Control.objects.filter(owner__username__in=DEMO_USERNAMES).count()

    def assert_programme_gone(self):
        from compliance.models import Control

        self.assertEqual(self.statuses(), {"not_started": Control.objects.count()})
        self.assertEqual(self.demo_owned(), 0)

    def test_retiring_the_demo_resets_the_control_programme_it_set(self):
        """remove_demo_data left the demo's 62 Implemented, 44 In progress and
        8 Not applicable controls in the register, 87 of them owned by the
        accounts it had just switched off, and said nothing about them."""
        from compliance.models import Control

        seeded = Control.objects.exclude(status=Control.Status.NOT_STARTED).count()
        owned = self.demo_owned()
        self.assertGreater(seeded, 100)
        self.assertGreater(owned, 60)

        out = self.remove()

        self.assert_programme_gone()
        self.assertIn(f"Seeded control statuses reset to Not started: {seeded}", out)
        self.assertIn(f"Controls owned by a demo account left with no owner: {owned}", out)

    def test_a_retired_workspace_scores_like_a_fresh_one(self):
        """The seed day's readiness point counted the links and risks the
        retirement deleted, and the dashboard read 17/100 on a register
        nobody had touched."""
        from django.utils import timezone

        from analytics.models import ReadinessSnapshot
        from analytics.snapshots import _measure

        fresh = Workspace.objects.create(name="Fresh Ltd", slug="fresh-score")
        call_command("seed_frameworks", "--with-folders", "--workspace", fresh.slug,
                     verbosity=0, stdout=StringIO())
        with tenancy.scoped(fresh):
            expected = _measure()

        self.remove()

        self.assertEqual(_measure(), expected)
        today = ReadinessSnapshot.objects.get(date=timezone.localdate())
        self.assertEqual(
            {k: getattr(today, k) for k in expected}, expected,
            "today's readiness point must not count the demo")

    def test_an_operators_changes_to_the_programme_are_left_alone(self):
        from compliance.models import Control

        User = get_user_model()
        realadmin = User.objects.get(username="realadmin")
        demoted = Control.objects.filter(status=Control.Status.IMPLEMENTED).first()
        demoted.status = Control.Status.IN_PROGRESS
        demoted.save()
        started = Control.objects.filter(status=Control.Status.NOT_STARTED).first()
        started.status = Control.Status.IMPLEMENTED
        started.save()
        taken = Control.objects.filter(status=Control.Status.IMPLEMENTED,
                                       owner__username="owen").first()
        taken.owner = realadmin
        taken.save()

        self.remove()

        demoted.refresh_from_db()
        started.refresh_from_db()
        taken.refresh_from_db()
        self.assertEqual(demoted.status, Control.Status.IN_PROGRESS, "the operator set it")
        self.assertEqual(started.status, Control.Status.IMPLEMENTED, "the operator set it")
        self.assertEqual(taken.owner, realadmin, "an owner of the operator's own stays")
        self.assertEqual(taken.status, Control.Status.NOT_STARTED, "the status was the demo's")
        self.assertEqual(self.demo_owned(), 0)
        self.assertEqual(self.statuses(), {
            "not_started": Control.objects.count() - 2, "in_progress": 1, "implemented": 1})

    def test_a_later_run_leaves_work_done_since_the_retirement_alone(self):
        """The run is idempotent. Once the programme is retired, a status the
        operator sets afterwards is theirs, even one the demo had set too."""
        from compliance.models import Control

        self.remove()
        first = Control.objects.order_by(
            "category__framework__key", "category__order", "control_id").first()
        first.status = Control.Status.IMPLEMENTED  # what the demo gave it, too
        first.save()

        out = self.remove()

        first.refresh_from_db()
        self.assertEqual(first.status, Control.Status.IMPLEMENTED)
        self.assertIn("Seeded control statuses reset to Not started: 0", out)

    def test_a_dry_run_counts_the_programme_and_changes_nothing(self):
        from compliance.models import Control

        before = self.statuses()
        seeded = Control.objects.exclude(status=Control.Status.NOT_STARTED).count()

        out = self.remove("--dry-run")

        self.assertIn(f"Seeded control statuses that would be reset to Not started: {seeded}", out)
        self.assertEqual(self.statuses(), before)
        self.assertGreater(self.demo_owned(), 0)

    def test_deleting_the_accounts_resets_the_programme_as_well(self):
        self.remove("--delete")
        self.assert_programme_gone()

    def test_a_demo_seeded_again_with_force_is_retired_again_in_full(self):
        from compliance.models import Control

        self.remove()
        self.boot("--force")
        self.assertGreater(Control.objects.exclude(status=Control.Status.NOT_STARTED).count(), 100)

        self.remove()

        self.assert_programme_gone()

    def test_force_after_real_work_leaves_that_work_and_its_history_alone(self):
        """Once the operator has set statuses of their own, --force applies
        no programme, so the next retirement has none to undo; and readiness
        points from before the revival are theirs, not the demo's."""
        from datetime import timedelta

        from django.utils import timezone

        from analytics.models import ReadinessSnapshot
        from compliance.models import Control

        self.remove()
        first = Control.objects.order_by(
            "category__framework__key", "category__order", "control_id").first()
        first.status = Control.Status.IMPLEMENTED
        first.save()
        earlier = timezone.localdate() - timedelta(days=10)
        ReadinessSnapshot.objects.create(date=earlier, total_controls=217, applicable=217,
                                         implemented=1, in_progress=0, with_evidence=0,
                                         evidence_links=0, documents_overdue=0, risks_open=0)
        self.boot("--force")

        out = self.remove()

        first.refresh_from_db()
        self.assertEqual(first.status, Control.Status.IMPLEMENTED)
        self.assertIn("Seeded control statuses reset to Not started: 0", out)
        self.assertTrue(ReadinessSnapshot.objects.filter(date=earlier).exists())

    def test_a_demo_seeded_by_an_older_release_is_reset_too(self):
        """Releases before this one kept no record of the programme. The
        seeder's pattern is read back instead, once the demo owners sit
        exactly where it put them."""
        from audit.models import AuditLog

        AuditLog.objects.filter(object_type="demo-controls").delete()
        self.remove()
        self.assert_programme_gone()

    def test_an_older_demo_on_a_changed_library_is_reported_not_guessed(self):
        """Without the record, a control added since the seed moves every
        position after it, so the pattern no longer says what the demo set:
        no status changes, and the command says what to do instead."""
        from audit.models import AuditLog
        from compliance.models import Control

        AuditLog.objects.filter(object_type="demo-controls").delete()
        first = Control.objects.order_by(
            "category__framework__key", "category__order", "control_id").first()
        Control.objects.create(category=first.category, control_id="0.0", title="Added later")
        before = self.statuses()

        out = self.remove()

        self.assertEqual(self.statuses(), before)
        self.assertEqual(self.demo_owned(), 0, "owners that cannot sign in still go")
        self.assertIn("Review the statuses on the Controls page", out)
        # Without the record the command cannot tell an added control from
        # owners changed by hand, so it names both and asserts neither.
        self.assertIn("controls were added or removed, or owners changed", out)

    def test_a_demo_an_older_release_retired_is_reported_not_reset(self):
        """0.9.5k and earlier retired the demo and left its programme. By now
        the operator's own work cannot be told apart from it, so the run
        names how many controls still hold the demo's status and changes
        none of them."""
        from audit.models import AuditLog
        from compliance.models import Control

        AuditLog.objects.filter(object_type="demo-controls").delete()
        AuditLog.objects.create(user=None, action="delete", object_type=RETIRED_OBJECT_TYPE,
                                detail="Demo dataset retired with remove_demo_data.")
        self.demo_accounts().update(is_active=False)
        seeded = Control.objects.exclude(status=Control.Status.NOT_STARTED).count()
        before = self.statuses()

        out = self.remove()

        self.assertEqual(self.statuses(), before)
        self.assertIn(f"left {seeded} controls with the status the demo gave them", out)
        self.assertIn("Review the statuses on the Controls page", out)
        self.assertEqual(self.demo_owned(), 0)

    # -- the warning when the statuses cannot be read back: its real cause ------
    @staticmethod
    def unrecorded():
        """A demo seeded by a release that kept no record of its programme."""
        from audit.models import AuditLog

        AuditLog.objects.filter(object_type="demo-controls").delete()

    def test_an_older_demo_whose_accounts_were_deleted_names_that_cause(self):
        """The warning blamed a change to the control library that never
        happened: here the library is as seeded, and the demo accounts, whose
        controls showed where the demo set its statuses, were deleted by
        hand."""
        self.unrecorded()
        self.demo_accounts().delete()
        before = self.statuses()

        out = self.remove()

        self.assertEqual(self.statuses(), before)
        self.assertIn("Seeded control statuses: not reset.", out)
        self.assertNotIn("library", out)
        self.assertIn("no demo account is left", out)
        self.assertIn("Review the statuses on the Controls page", out)

    def test_an_older_demo_whose_owners_were_cleared_names_that_cause(self):
        from compliance.models import Control

        self.unrecorded()
        Control.objects.update(owner=None)
        before = self.statuses()

        out = self.remove()

        self.assertEqual(self.statuses(), before)
        self.assertNotIn("library", out)
        self.assertIn("no control is owned by a demo account any more", out)

    def test_a_changed_library_is_named_only_when_it_is_the_cause(self):
        """With the demo's record, a control the programme walked that is
        gone proves the library changed, and the warning says so."""
        from compliance.models import Control
        from accounts.management.commands.bootstrap_demo import PROGRAMME_ORDER

        Control.objects.order_by(*PROGRAMME_ORDER).first().delete()
        before = self.statuses()

        out = self.remove()

        self.assertEqual(self.statuses(), before)
        self.assertIn("removed from the control library or reordered in it", out)
        self.assertNotIn("older release", out)

    def test_an_unreadable_record_is_named_as_the_cause(self):
        from audit.models import AuditLog

        AuditLog.objects.filter(object_type="demo-controls").update(object_id="", detail="")
        before = self.statuses()

        out = self.remove()

        self.assertEqual(self.statuses(), before)
        self.assertNotIn("library", out)
        self.assertIn("The demo's record of the statuses it set cannot be read.", out)

    # -- the programme's record in the Audit log --------------------------------
    def test_the_programme_record_reads_as_plain_words_in_the_audit_log(self):
        """Its Detail showed '[programme last=217 order=852463c1ee835202]' to
        whoever read the Audit log, and it stays there after the retirement.
        What remove_demo_data reads back sits in the record reference."""
        from rest_framework.test import APIClient

        self.remove()

        client = APIClient()
        client.force_authenticate(get_user_model().objects.get(username="realadmin"))
        rows = client.get("/api/audit-log/", {"object_type": "demo-controls"}).json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertEqual(len(rows), 1)
        detail = rows[0]["detail"]
        self.assertTrue(detail.startswith("Demo control programme set statuses and owners on "),
                        detail)
        self.assertNotRegex(detail, r"\[|\]|programme last|order=|[0-9a-f]{16}")
        self.assertRegex(rows[0]["object_id"], r"^\d+-[0-9a-f]{16}$")
        self.assert_programme_gone()

    # -- the readiness history of a demo seeded again ---------------------------
    def test_retire_force_retire_on_one_day_leaves_no_demo_history(self):
        """--force on the day of a retirement found no readiness point dated
        before today and back-filled five invented months into the real
        installation's trend; the next retirement, bounded by the revival,
        never deleted them."""
        from django.utils import timezone

        from analytics.models import ReadinessSnapshot

        self.remove()
        revived = self.boot("--force")
        self.boot()  # a container restart the same day refreshes the revived demo
        out = self.remove()

        today = timezone.localdate()
        self.assertEqual(list(ReadinessSnapshot.objects.values_list("date", flat=True)), [today])
        self.assertEqual(ReadinessSnapshot.objects.get(date=today).implemented, 0)
        self.assertNotIn("Readiness history:", revived)
        self.assertIn("Seeded readiness history points deleted: 0", out)
        self.assert_programme_gone()

    def test_history_recorded_since_a_revival_goes_with_the_next_retirement(self):
        """Points from before the revival are the operator's; the ones the
        revived demo recorded are not."""
        from datetime import timedelta

        from django.utils import timezone

        from analytics.models import ReadinessSnapshot
        from audit.models import AuditLog

        self.remove()
        today = timezone.localdate()
        theirs = today - timedelta(days=20)
        demo = today - timedelta(days=5)
        ReadinessSnapshot.objects.create(date=theirs, total_controls=217, applicable=217)
        self.boot("--force")
        AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE, action="create").update(
            timestamp=timezone.now() - timedelta(days=10))
        ReadinessSnapshot.objects.create(date=demo, total_controls=217, applicable=217,
                                         implemented=60)

        out = self.remove()

        self.assertEqual(set(ReadinessSnapshot.objects.values_list("date", flat=True)),
                         {theirs, today})
        self.assertIn("Seeded readiness history points deleted: 1", out)


class DemoOnAWorkedRegisterTests(TestCase):
    """bootstrap_demo run after the operator had set statuses of their own:
    it applies no control programme, so retiring it has no status of the
    demo's to reset and nothing to warn about. The warning used to name a
    cause that was not true here either."""

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

    def test_the_operators_statuses_stay_and_no_warning_is_given(self):
        from audit.models import AuditLog
        from compliance.models import Control
        from accounts.management.commands.bootstrap_demo import PROGRAMME_ORDER

        # Position 0 is one the demo would mark Implemented.
        first = Control.objects.order_by(*PROGRAMME_ORDER).first()
        first.status = Control.Status.IN_PROGRESS
        first.save()
        seeded = StringIO()
        call_command("bootstrap_demo", stdout=seeded)
        self.assertIn("Control programme: already set, left alone", seeded.getvalue())
        make_user("realadmin", superuser=True)

        out = StringIO()
        call_command("remove_demo_data", stdout=out)

        first.refresh_from_db()
        self.assertEqual(first.status, Control.Status.IN_PROGRESS)
        self.assertEqual(Control.objects.exclude(status=Control.Status.NOT_STARTED).count(), 1)
        self.assertNotIn("Review the statuses", out.getvalue())
        self.assertIn("Seeded control statuses reset to Not started: 0", out.getvalue())
        # The seed said so in the Audit log, in words.
        record = AuditLog.objects.get(object_type="demo-controls")
        self.assertIn("not applied", record.detail)
        self.assertNotRegex(record.detail, r"\[|[0-9a-f]{16}")

    def test_a_refresh_boot_writes_no_second_record(self):
        """Only the seed that starts the demo says the programme was not
        applied; the boots that refresh it add nothing, so a demo an older
        release seeded is still read back from its pattern."""
        from audit.models import AuditLog
        from compliance.models import Control

        Control.objects.update(status=Control.Status.IN_PROGRESS)
        call_command("bootstrap_demo", stdout=StringIO())
        call_command("bootstrap_demo", stdout=StringIO())
        self.assertEqual(AuditLog.objects.filter(object_type="demo-controls").count(), 1)


class NoDemoRetirementTests(TestCase):
    """remove_demo_data run where the demo was never seeded: nothing of the
    operator's is the demo's, so no status changes and no readiness history
    goes (a run used to delete every point dated before today)."""

    def test_the_operators_statuses_and_history_stay(self):
        from datetime import timedelta

        from django.utils import timezone

        from analytics.models import ReadinessSnapshot
        from compliance.models import Control

        call_command("seed_frameworks", "--with-folders", verbosity=0, stdout=StringIO())
        make_user("realadmin", superuser=True)
        # Position 0 is one the demo marks Implemented; here the operator did.
        first = Control.objects.order_by(
            "category__framework__key", "category__order", "control_id").first()
        first.status = Control.Status.IMPLEMENTED
        first.save()
        earlier = timezone.localdate() - timedelta(days=30)
        ReadinessSnapshot.objects.create(date=earlier, total_controls=217, applicable=217,
                                         implemented=1)

        out = StringIO()
        call_command("remove_demo_data", stdout=out)

        first.refresh_from_db()
        self.assertEqual(first.status, Control.Status.IMPLEMENTED)
        self.assertTrue(ReadinessSnapshot.objects.filter(date=earlier).exists())
        self.assertIn("Seeded control statuses reset to Not started: 0", out.getvalue())
        self.assertIn("Seeded readiness history points deleted: 0", out.getvalue())
        self.assertNotIn("Review the statuses", out.getvalue())


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

    def test_the_demo_step_does_not_announce_a_seed_it_may_not_make(self):
        """On a retired workspace every boot logged "Seeding demo dataset"
        and, on the next line, bootstrap_demo's "Demo data not seeded"."""
        self.assertFalse("Seeding demo dataset" in self.source, "the old announcement is back")
        self.assertIn('log "SEED_DEMO_DATA=true: running bootstrap_demo', self.source)

    def test_no_boot_line_uses_a_dash(self):
        said = re.findall(r'^\s*(?:log|print\()\s*[f]?"(.*)"', self.source, re.M)
        self.assertGreater(len(said), 20)
        for line in said:
            self.assertNotRegex(line, r"\s-{1,2}\s|[\u2013\u2014]", line)


def _demo_admin():
    """The seeded administrator as /api/health/ and remove_demo_data know it:
    named admin, with an @example.com address."""
    return make_user("admin", superuser=True, email="admin@example.com")


class OwnAdministratorTests(TestCase):
    """own_administrator_present: remove_demo_data's guard, and the question
    the seeder's advice and the boot banner ask before naming createsuperuser."""

    def setUp(self):
        from accounts.management.commands.bootstrap_demo import own_administrator_present

        self.present = lambda: own_administrator_present(tenancy.default_workspace())
        _demo_admin()

    def test_the_demo_administrator_is_nobody_s_own(self):
        self.assertFalse(self.present())

    def test_a_superuser_of_the_workspace_or_of_none_counts(self):
        User = get_user_model()
        root = make_user("root", superuser=True)
        self.assertTrue(self.present())
        with tenancy.unscoped():
            User.objects.filter(pk=root.pk).update(workspace=None)
        self.assertTrue(self.present(), "a superuser detached by hand still counts")
        with tenancy.unscoped():
            User.objects.filter(pk=root.pk).update(is_active=False)
        self.assertFalse(self.present(), "an inactive one administers nothing")

    def test_a_user_managing_role_counts_and_an_auditor_role_does_not(self):
        from accounts.models import Role

        auditing = Role.objects.create(name="Auditing admin", can_manage_users=True, is_auditor=True)
        make_user("outside-auditor", role=auditing)
        self.assertFalse(self.present())
        people = Role.objects.create(name="People admin", can_manage_users=True)
        make_user("people", role=people)
        self.assertTrue(self.present())

    def test_an_administrator_of_another_workspace_is_not_this_one_s(self):
        """remove_demo_data cleans one workspace and asks about that one."""
        from accounts.models import Role

        other = Workspace.objects.create(name="Beta Ltd", slug="beta-own-admin")
        with tenancy.scoped(other):
            role = Role.objects.create(name="People admin", can_manage_users=True)
            make_user("beta-manager", role=role)
        self.assertFalse(self.present())


class EntrypointDemoAdviceTests(TestCase):
    """The boot banner's demo lines, run as the entrypoint runs them (the
    Python between `python - <<'PY'` and `PY` at the end of entrypoint.sh),
    against this test's database. It told an operator to run remove_demo_data,
    which then refused because no administrator of their own existed yet."""

    source = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(encoding="utf-8")

    def banner(self):
        start = self.source.index("python - <<'PY'\nimport os\nfrom config.version")
        body = self.source[start:].split("\n", 1)[1]
        code = body[:body.index("\nPY\n")]
        out = StringIO()
        # django.setup() has already run in this process; the banner's call
        # would only configure logging again.
        with mock.patch("django.setup"), mock.patch.dict(os.environ, {"DJANGO_DEBUG": "false"}), \
                contextlib.redirect_stdout(out):
            exec(compile(code, "entrypoint.sh banner", "exec"), {"__name__": "__main__"})
        return out.getvalue()

    def test_createsuperuser_comes_first_while_the_demo_holds_the_only_administrator(self):
        _demo_admin()
        out = self.banner()
        self.assertIn("demo accounts=ON", out)
        self.assertNotIn("No administrator exists yet", out, "the demo admin is an administrator")
        first = out.index("manage.py createsuperuser")
        self.assertLess(first, out.index("manage.py remove_demo_data"))
        self.assertIn("refuses until one exists", out)

    def test_with_an_administrator_of_ones_own_it_is_the_one_command(self):
        _demo_admin()
        make_user("root", superuser=True)
        out = self.banner()
        self.assertIn("docker compose exec backend python manage.py remove_demo_data", out)
        self.assertNotIn("createsuperuser", out)

    def test_a_failed_lookup_gives_the_advice_that_is_right_either_way(self):
        _demo_admin()
        make_user("root", superuser=True)
        with mock.patch("accounts.management.commands.bootstrap_demo.own_administrator_present",
                        side_effect=RuntimeError("database gone")):
            out = self.banner()
        self.assertLess(out.index("manage.py createsuperuser"), out.index("manage.py remove_demo_data"))

    def test_no_demo_no_demo_advice(self):
        make_user("root", superuser=True)
        out = self.banner()
        self.assertIn("demo accounts=off", out)
        self.assertNotIn("remove_demo_data", out)
