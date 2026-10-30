"""Regression tests for findings in REVIEWS.md (0.9.0 review); each class names its finding."""
from django.conf import settings
from django.test import TestCase, override_settings

from accounts import mfa as mfa_lib
from accounts import tenancy
from accounts.models import MfaBackupCode, MfaDevice, Workspace
from testutils import APITestBase, make_user


class TotpReplayTests(TestCase):
    """Medium 4: a spent code must not stay good for its whole window: TOTP is valid for 30 seconds plus a step of
    drift either way, so six digits lifted from a phishing form would work again for up to 90 seconds."""

    def setUp(self):
        self.user = make_user("totp-user")
        self.secret = mfa_lib.generate_secret()
        self.device = MfaDevice.objects.create(user=self.user, secret=self.secret, enabled=True)

    def test_a_code_is_accepted_once(self):
        code = mfa_lib.totp(self.secret)
        self.assertTrue(self.device.verify(code))
        self.assertFalse(self.device.verify(code), "the same code authenticated twice")

    def test_a_stale_object_cannot_replay_it(self):
        """Two requests hold their own copies of the row, so the claim has to happen in the database, not in Python."""
        code = mfa_lib.totp(self.secret)
        first = MfaDevice.objects.get(pk=self.device.pk)
        second = MfaDevice.objects.get(pk=self.device.pk)
        self.assertTrue(first.verify(code))
        self.assertFalse(second.verify(code))

    def test_an_earlier_code_still_inside_the_window_is_refused(self):
        """The window looks backwards too: accepting the previous step after the current one would reopen the replay."""
        import time

        now = time.time()
        self.assertTrue(self.device.verify(mfa_lib.totp(self.secret, at=now)))
        self.assertFalse(self.device.verify(mfa_lib.totp(self.secret, at=now - mfa_lib.PERIOD)))

    def test_the_next_window_still_works(self):
        import time

        now = time.time()
        self.assertTrue(self.device.verify(mfa_lib.totp(self.secret, at=now)))
        self.assertTrue(self.device.verify(mfa_lib.totp(self.secret, at=now + mfa_lib.PERIOD)))

    def test_a_wrong_code_spends_nothing(self):
        self.assertFalse(self.device.verify("000000"))
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_counter, 0)
        self.assertTrue(self.device.verify(mfa_lib.totp(self.secret)))


class BackupCodeClaimTests(TestCase):
    """Low 9: a backup code is claimed atomically, or one code could authenticate two sign-ins that arrive together."""

    def setUp(self):
        self.user = make_user("codes-user")
        self.codes = self.user.issue_backup_codes()

    def test_a_code_works_once(self):
        self.assertTrue(self.user.verify_backup_code(self.codes[0]))
        self.assertFalse(self.user.verify_backup_code(self.codes[0]))

    def test_a_concurrent_second_use_loses(self):
        """Both callers see an unused row; only the UPDATE that matches ``used_at IS NULL`` may return true."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        one = User.objects.get(pk=self.user.pk)
        two = User.objects.get(pk=self.user.pk)
        self.assertTrue(one.verify_backup_code(self.codes[1]))
        self.assertFalse(two.verify_backup_code(self.codes[1]))
        self.assertEqual(MfaBackupCode.objects.filter(used_at__isnull=False).count(), 1)

    def test_the_other_codes_survive(self):
        self.assertTrue(self.user.verify_backup_code(self.codes[2]))
        self.assertEqual(self.user.backup_codes_remaining, len(self.codes) - 1)
        self.assertTrue(self.user.verify_backup_code(self.codes[3]))


class SlicedQuerysetTests(TestCase):
    """Low 2: _pin() must not skip an already-sliced queryset: one built with no workspace active and read inside one
    would return every organisation's rows, so it refuses."""

    def setUp(self):
        self.a = tenancy.default_workspace()
        self.b = Workspace.objects.create(name="Beta", slug="beta-slice")
        with tenancy.scoped(self.a):
            make_user("in-a")
        with tenancy.scoped(self.b):
            make_user("in-b")

    def test_a_slice_taken_unscoped_and_read_scoped_is_refused(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        with tenancy.unscoped():
            sliced = User.objects.order_by("pk")[:10]
        with tenancy.scoped(self.b):
            with self.assertRaises(tenancy.UnscopedRead):
                list(sliced)
            with self.assertRaises(tenancy.UnscopedRead):
                sliced.count()

    def test_a_slice_taken_inside_the_workspace_is_scoped(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        with tenancy.scoped(self.b):
            names = [u.username for u in User.objects.order_by("pk")[:10]]
        self.assertEqual(names, ["in-b"])

    def test_reading_it_unscoped_on_purpose_still_works(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        with tenancy.unscoped():
            sliced = User.objects.order_by("pk")[:10]
            self.assertIn("in-a", [u.username for u in sliced])


class ComplianceInboxTests(TestCase):
    """Low 1: each organisation's reminders go to its own address: the subject lines carry document and vendor names,
    so one installation-wide mailbox would publish every tenant's business to whoever runs the box."""

    def setUp(self):
        self.a = tenancy.default_workspace()
        self.b = Workspace.objects.create(
            name="Beta", slug="beta-inbox", notification_email="grc@beta.example")

    @override_settings(COMPLIANCE_TEAM_EMAIL="fallback@install.local")
    def test_each_workspace_gets_its_own(self):
        from notifications.tasks import compliance_inbox

        with tenancy.scoped(self.b):
            self.assertEqual(compliance_inbox(), "grc@beta.example")

    @override_settings(COMPLIANCE_TEAM_EMAIL="fallback@install.local")
    def test_a_workspace_without_one_falls_back(self):
        """A single-organisation install configures nothing and is unchanged."""
        from notifications.tasks import compliance_inbox

        with tenancy.scoped(self.a):
            self.assertEqual(compliance_inbox(), "fallback@install.local")
        self.assertEqual(compliance_inbox(), "fallback@install.local")


class SsoAssertionDefaultTests(TestCase):
    """Low 4: the shipped list of asserted second factors must not include the two RFC 8176 values that are not."""

    def test_user_presence_and_pin_are_not_second_factors(self):
        self.assertNotIn("user", settings.SSO_MFA_ASSERTIONS,
                         "amr=user is a presence test: somebody touched the key")
        self.assertNotIn("pin", settings.SSO_MFA_ASSERTIONS,
                         "amr=pin may well be the IdP's *first* factor")

    def test_the_real_ones_are_still_there(self):
        for value in ("mfa", "otp", "hwk", "fido"):
            self.assertIn(value, settings.SSO_MFA_ASSERTIONS)


class AuditorRoleDescriptionTests(APITestBase):
    """High 13: the shipped description must promise only what the code enforces."""

    def test_the_description_no_longer_claims_folders_are_the_limit(self):
        description = self.roles["Auditor"].description
        self.assertNotIn("only granted folders", description)
        self.assertIn("packages issued to them", description)
