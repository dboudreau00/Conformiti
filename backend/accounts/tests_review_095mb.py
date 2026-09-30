"""Defects a documentation audit found before a partner security review,
fixed in 0.9.5mb. Each class names the documented control the code did not
deliver; see REVIEWS.md and SECURITY.md."""
import time
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import Client, RequestFactory, override_settings
from rest_framework.test import APIClient

from accounts import mfa as mfa_lib
from accounts.models import MfaDevice, Role, User, Workspace
from attestations.tests import PackageTestBase
from attestations.views import PackageWorkThrottle
from audit.middleware import _client_ip
from audit.models import AuditLog
from testutils import PASSWORD, APITestBase

STRONG = "Correct-Horse-Battery-9"


def _enable_totp(test, user):
    c = test.client_for(user)
    secret = c.post("/api/auth/mfa/setup/", {"password": PASSWORD}, format="json").data["secret"]
    r = c.post("/api/auth/mfa/verify/", {"code": mfa_lib.totp(secret), "password": PASSWORD}, format="json")
    test.assertEqual(r.status_code, 200, r.data)
    return c, secret, r.data["backup_codes"]


def _admin_client(user):
    c = Client()
    c.force_login(user)
    return c


class UnreadableTotpSecretTests(APITestBase):
    """A secret the field-encryption ring cannot decrypt reads as "", and the
    code of an empty key is one anyone can compute. SECURITY.md says this
    state degrades safely; it accepted that code as the second factor."""

    def empty_key_code(self):
        # The next time step, which the drift window accepts: the current one
        # was just spent by the enrolment, and the replay guard would refuse
        # it whatever the key.
        return mfa_lib.hotp("", int(time.time() // mfa_lib.PERIOD) + 1)

    def test_the_library_refuses_an_empty_key(self):
        self.assertIsNone(mfa_lib.matched_counter("", self.empty_key_code()))
        self.assertFalse(mfa_lib.verify("", self.empty_key_code()))

    def test_an_unreadable_secret_refuses_every_code_and_backup_codes_still_work(self):
        _, _, codes = _enable_totp(self, self.manager)
        device_pk = self.manager.mfa_device.pk
        with mock.patch("config.fieldcrypto.decrypt", return_value=None):
            device = MfaDevice.objects.get(pk=device_pk)
            self.assertEqual(device.secret, "", "the state under test: the ring cannot read it")
            self.assertFalse(device.verify(self.empty_key_code()))
            anon = APIClient()
            r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD,
                                               "otp": self.empty_key_code()}, format="json")
            self.assertEqual(r.status_code, 401)
            cache.clear()
            r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD,
                                               "otp": codes[0]}, format="json")
            self.assertEqual(r.status_code, 200, r.data)


class HealthOverPlainHttpTests(APITestBase):
    """With BEHIND_TLS on, SECURE_SSL_REDIRECT answered the image's own
    HEALTHCHECK (plain HTTP to 127.0.0.1:8000) with a 301, so the backend was
    never healthy and compose started nothing that waits for it."""

    def test_health_answers_plain_http_and_the_rest_still_redirects(self):
        self.assertEqual(settings.SECURE_REDIRECT_EXEMPT, [r"^api/health/$"])
        with override_settings(SECURE_SSL_REDIRECT=True):
            c = Client()
            self.assertEqual(c.get("/api/health/").status_code, 200)
            r = c.get("/api/auth/config/")
            self.assertEqual(r.status_code, 301)
            self.assertTrue(r["Location"].startswith("https://"))


class AdminTrailReadOnlyTests(APITestBase):
    """The Django admin could delete audit entries, one at a time or with
    "Delete selected", and delete a workspace with its whole trail."""

    def test_no_superuser_can_edit_or_delete_an_entry(self):
        entry = AuditLog.objects.create(user=self.manager, action="update", object_type="documents",
                                        detail="PATCH /api/documents/1/")
        admin = _admin_client(self.admin)
        self.assertEqual(admin.get(f"/admin/audit/auditlog/{entry.pk}/delete/").status_code, 403)
        admin.post("/admin/audit/auditlog/", {"action": "delete_selected",
                                               "_selected_action": [entry.pk], "post": "yes"})
        admin.post(f"/admin/audit/auditlog/{entry.pk}/change/", {"detail": "rewritten"})
        entry.refresh_from_db()
        self.assertEqual(entry.detail, "PATCH /api/documents/1/")
        self.assertEqual(admin.get(f"/admin/audit/auditlog/{entry.pk}/change/").status_code, 200)

    def test_a_workspace_cannot_be_deleted_in_the_admin(self):
        workspace = Workspace.objects.create(name="Beta Ltd", slug="beta-admin")
        admin = _admin_client(self.admin)
        self.assertEqual(admin.get(f"/admin/accounts/workspace/{workspace.pk}/delete/").status_code, 403)
        self.assertTrue(Workspace.objects.filter(pk=workspace.pk).exists())


class AdminPasswordPageTests(APITestBase):
    """The hook meant to end sessions on an administrator's password set sat
    in save_model, which the admin's password page never calls."""

    def test_a_password_set_on_the_admin_page_ends_sessions_and_is_audited(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework_simplejwt.tokens import AccessToken

        # Issued before the reset. The stamp is floored to the second by
        # design, so a token from the same second still passes.
        token = AccessToken.for_user(self.viewer)
        token.set_iat(at_time=timezone.now() - timedelta(seconds=5))
        tokens = {"access": str(token)}
        admin = _admin_client(self.admin)
        r = admin.post(f"/admin/accounts/user/{self.viewer.pk}/password/",
                       {"password1": STRONG, "password2": STRONG})
        self.assertEqual(r.status_code, 302)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password(STRONG))
        self.assertIsNotNone(self.viewer.sessions_valid_from)
        old = APIClient()
        old.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(old.get("/api/users/me/").status_code, 401)
        entry = AuditLog.objects.filter(action="password", user=self.viewer).first()
        self.assertIsNotNone(entry)
        self.assertIn("set in the admin by ada", entry.detail)
        self.assertNotIn(STRONG, entry.detail)

    def test_a_refused_password_changes_nothing(self):
        admin = _admin_client(self.admin)
        r = admin.post(f"/admin/accounts/user/{self.viewer.pk}/password/",
                       {"password1": STRONG, "password2": "different"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(AuditLog.objects.filter(action="password", user=self.viewer).exists())


class PackageWorkThrottleTests(PackageTestBase):
    """THROTTLE_PACKAGE_WORK was never applied: a ScopedRateThrottle with no
    view throttle_scope lets every request through."""

    def test_seal_and_export_share_the_documented_per_account_limit(self):
        with mock.patch.object(PackageWorkThrottle, "THROTTLE_RATES", {"package_work": "3/min"}):
            self.add_control()
            self.seal()
            url = f"/api/evidence-packages/{self.package.pk}/export/"
            self.assertEqual(self.manager_client.get(url).status_code, 200)
            self.assertEqual(self.manager_client.get(url).status_code, 200)
            self.assertEqual(self.manager_client.get(url).status_code, 429)
            # Per account: another person with the capability is unaffected.
            other = self.client_for(self.admin)
            self.assertEqual(other.get(url).status_code, 200)


class AuditClientAddressTests(APITestBase):
    """The trail took the rightmost X-Forwarded-For entry whatever NUM_PROXIES
    said, so behind a terminator in front of the shipped nginx it recorded the
    terminator for every client. It now chooses as the rate limits do."""

    def ip_with(self, proxies, xff="203.0.113.5, 10.0.0.2", remote="10.0.0.3"):
        rest = dict(settings.REST_FRAMEWORK, NUM_PROXIES=proxies)
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR=remote)
        with override_settings(REST_FRAMEWORK=rest):
            return _client_ip(request)

    def test_the_address_follows_num_proxies(self):
        self.assertEqual(self.ip_with(2), "203.0.113.5")
        self.assertEqual(self.ip_with(1), "10.0.0.2")
        self.assertEqual(self.ip_with(0), "10.0.0.3")
        self.assertEqual(self.ip_with(2, xff=None), "10.0.0.3")
        self.assertIsNone(self.ip_with(1, xff="not-an-address"))

    def test_a_sign_in_behind_two_proxies_records_the_client(self):
        rest = dict(settings.REST_FRAMEWORK, NUM_PROXIES=2)
        with override_settings(REST_FRAMEWORK=rest):
            APIClient().post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json",
                             HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.2", REMOTE_ADDR="10.0.0.3")
        self.assertEqual(AuditLog.objects.filter(action="login").latest("pk").ip_address, "203.0.113.5")


class SecondFactorTrailTests(APITestBase):
    """Turning the authenticator on and off and regenerating backup codes
    wrote nothing: /api/auth/ is outside the request middleware, and these
    views recorded no event of their own."""

    def mfa_details(self):
        return list(AuditLog.objects.filter(action="mfa", user=self.manager)
                    .order_by("pk").values_list("detail", flat=True))

    def test_enrol_regenerate_and_remove_are_each_recorded(self):
        c, _secret, _codes = _enable_totp(self, self.manager)
        self.assertEqual(c.post("/api/auth/mfa/backup-codes/", {"password": PASSWORD},
                                format="json").status_code, 200)
        self.assertEqual(c.post("/api/auth/mfa/disable/", {"password": PASSWORD},
                                format="json").status_code, 200)
        self.assertEqual(self.mfa_details(), [
            "authenticator app enrolled; backup codes issued",
            "backup codes regenerated (the previous set no longer works)",
            "authenticator app removed; backup codes deleted",
        ])


class RefusedSignInTrailTests(APITestBase):
    """A sign-in the rate limit refused never reached the trail: DRF refuses
    it before the view's post(), where every other attempt is recorded."""

    def test_a_throttled_attempt_is_recorded_once_a_window(self):
        c = APIClient()
        for _ in range(12):
            c.post("/api/auth/token/", {"username": "mia", "password": "wrong"}, format="json")
        failed = list(AuditLog.objects.filter(action="login_failed").values_list("detail", flat=True))
        self.assertEqual(sum("throttled" in d for d in failed), 1)
        self.assertEqual(sum("invalid credentials" in d for d in failed), 8)


class AdminActivityTrailTests(APITestBase):
    """Sign-ins to the Django admin, and what was saved there, reached the
    trail only for a password set and a refused second factor."""

    def test_admin_sign_ins_are_recorded_both_ways(self):
        Client().post("/admin/login/", {"username": "ada", "password": "wrong"})
        Client().post("/admin/login/", {"username": "ada", "password": PASSWORD})
        details = list(AuditLog.objects.filter(object_type="auth")
                       .order_by("pk").values_list("action", "detail"))
        self.assertIn(("login_failed", "Django admin sign-in failed for ada: "
                                       "invalid credentials or not a staff account"), details)
        self.assertIn(("login", "signed in to the Django admin: ada"), details)
        self.assertFalse(any("wrong" in d or PASSWORD in d for _, d in details))

    def test_a_save_in_the_admin_is_recorded(self):
        role = Role.objects.create(name="Temporary")
        admin = _admin_client(self.admin)
        r = admin.post(f"/admin/accounts/role/{role.pk}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 302)
        entry = AuditLog.objects.filter(object_type="admin:accounts.role").latest("pk")
        self.assertEqual((entry.action, entry.object_id, entry.user_id), ("delete", str(role.pk), self.admin.pk))
        self.assertNotIn("csrfmiddlewaretoken", entry.detail)

    def test_a_form_that_is_refused_is_not_recorded(self):
        admin = _admin_client(self.admin)
        admin.post(f"/admin/accounts/user/{self.viewer.pk}/change/", {"username": ""})
        self.assertFalse(AuditLog.objects.filter(object_type="admin:accounts.user").exists())


class SigningFingerprintTests(PackageTestBase):
    """Settings > About and /api/health/ showed the installation's root key,
    which signs nothing: every package is signed with a key derived for its
    workspace. Operators were told to hand auditors that fingerprint."""

    def test_health_names_the_key_a_package_carries_on_a_single_workspace(self):
        self.add_control()
        self.seal()
        body = APIClient().get("/api/health/").data["signing"]
        self.assertEqual(body["key_id"], self.package.signing_key_id)
        self.assertFalse(body["per_workspace"])

    def test_with_several_organisations_health_names_none_and_the_screen_asks(self):
        Workspace.objects.create(name="Beta Ltd", slug="beta-signing")
        body = APIClient().get("/api/health/").data["signing"]
        self.assertEqual((body["key_id"], body["fingerprint"], body["per_workspace"]), (None, None, True))
        self.add_control()
        self.seal()
        mine = self.manager_client.get("/api/signing-keys/current/").data
        self.assertEqual(mine["key_id"], self.package.signing_key_id)
        self.assertEqual(mine["fingerprint"][:16], mine["key_id"])
        self.assertIsNone(mine["error"])

    def test_an_external_auditor_is_refused_the_current_key(self):
        self.assertEqual(self.client_for(self.auditor).get("/api/signing-keys/current/").status_code, 403)
        self.assertEqual(APIClient().get("/api/signing-keys/current/").status_code, 401)
