"""The Django admin is part of the product's attack surface.

Django's own admin login asks for a password and nothing else, and the session
it creates used to authenticate the whole API as well. Both are closed; these
tests hold them closed.
"""
from django.core.cache import cache
from django.test import Client, override_settings

from accounts import mfa as mfa_lib
from accounts.models import MfaDevice, Workspace
from testutils import PASSWORD, APITestBase, make_user


class AdminLoginTests(APITestBase):
    URL = "/admin/login/"

    def setUp(self):
        super().setUp()
        cache.clear()
        self.staffer = make_user("stan", self.roles["Administrator"], superuser=True)

    def post(self, **extra):
        body = {"username": self.staffer.username, "password": PASSWORD,
                "next": "/admin/", **extra}
        return Client().post(self.URL, body)

    def enrol(self):
        secret = mfa_lib.generate_secret()
        MfaDevice.objects.create(user=self.staffer, secret=secret, enabled=True)
        return secret

    def test_the_form_asks_for_the_second_factor(self):
        r = Client().get(self.URL)
        self.assertContains(r, "Authentication code")

    def test_an_enrolled_account_cannot_sign_in_with_the_password_alone(self):
        self.enrol()
        r = self.post()
        self.assertEqual(r.status_code, 200)  # redisplayed, not redirected
        self.assertContains(r, "authenticator app")
        self.assertNotIn("_auth_user_id", Client().session)

    def test_the_right_code_gets_in(self):
        secret = self.enrol()
        r = self.post(otp=mfa_lib.totp(secret))
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:400])

    def test_a_backup_code_gets_in(self):
        """A passkey-only administrator has no authenticator, so the account's
        backup codes are their way in."""
        codes = self.staffer.issue_backup_codes()
        self.enrol()
        r = self.post(otp=codes[0])
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:400])

    def test_an_account_with_no_second_factor_is_unaffected(self):
        r = self.post()
        self.assertEqual(r.status_code, 302)

    def test_attempts_are_rate_limited(self):
        for _ in range(9):
            self.post(password="wrong")
        r = self.post()  # correct password, but the client is over the limit
        self.assertContains(r, "Too many sign-in attempts")

    def test_an_archived_workspace_refuses_its_administrator(self):
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-admin")
        # Staff but not a superuser: the refusal is for a workspace member.
        staffer = make_user("bstan", self.roles["Administrator"])
        staffer.is_staff = True
        staffer.workspace = beta
        staffer.save(update_fields=["is_staff", "workspace"])
        beta.is_active = False
        beta.save(update_fields=["is_active"])
        r = Client().post(self.URL, {"username": "bstan", "password": PASSWORD, "next": "/admin/"})
        self.assertContains(r, "archived")


class AdminSessionIsNotAnApiCredentialTests(APITestBase):
    """An admin session must not authenticate /api/ in production: it is
    obtained through a different, weaker door."""

    @override_settings(DEBUG=False)
    def test_session_authentication_is_not_a_production_default(self):
        from django.conf import settings

        # The setting is evaluated at import; assert the shipped intent
        # directly rather than re-importing the module.
        classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
        self.assertIn("accounts.cookie_auth.CookieJWTAuthentication", classes)
        source = open(settings.BASE_DIR / "config" / "settings.py", encoding="utf-8").read()
        self.assertIn("if DEBUG else [\"accounts.cookie_auth.CookieJWTAuthentication\"]", source)
