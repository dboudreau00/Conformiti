"""The fourth independent review, fixed in 0.9.5f.

H-1 a hijacked session could enrol its own authenticator · H-2 a self-edited
email decided who an identity provider linked to · M-3 the cross-tenant
username check never left the tenant · M-4 a password reset left the access
token alive · M-5 the two endpoints that set the auth cookies were the two
that never checked CSRF · M-6 an account with no password could not remove a
factor.

H-3 (the published image booted with DEBUG on) is a property of the image
rather than of the code, so it is held by the workflow that builds it and by
``tools/validate.py``. M-1 lives in ``tests_auditor_surface`` beside the walk
it extends, and M-2 in ``documents.tests_uploads``.
"""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from accounts import tenancy
from accounts.models import Workspace
from testutils import PASSWORD, APITestBase, make_user


class ReauthOnEveryFactorChangeTests(APITestBase):
    """H-1 and M-6. Adding a passkey has asked the caller to prove the account
    is theirs since 0.9.5; enrolling an authenticator app asked for nothing,
    which is the same hole and a worse one. A stolen session enrolled its own
    app, took the backup codes, and left the owner locked out of an account
    the attacker could still reach."""

    def test_setup_without_proof_is_refused(self):
        r = self.client_for(self.owner).post("/api/auth/mfa/setup/", {}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data.get("code"), "reauth_required")
        self.assertFalse(hasattr(self.owner, "mfa_device") and self.owner.mfa_device)

    def test_setup_with_the_password_is_allowed(self):
        r = self.client_for(self.owner).post(
            "/api/auth/mfa/setup/", {"password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("secret", r.data)

    def test_verify_without_proof_is_refused(self):
        client = self.client_for(self.owner)
        started = client.post("/api/auth/mfa/setup/", {"password": PASSWORD}, format="json")
        from accounts import mfa as mfa_lib

        code = mfa_lib.totp(started.data["secret"])
        r = client.post("/api/auth/mfa/verify/", {"code": code}, format="json")
        self.assertEqual(r.status_code, 403)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.mfa_enabled)

    def test_the_whole_enrolment_works_with_the_password(self):
        client = self.client_for(self.owner)
        started = client.post("/api/auth/mfa/setup/", {"password": PASSWORD}, format="json")
        from accounts import mfa as mfa_lib

        code = mfa_lib.totp(started.data["secret"])
        r = client.post("/api/auth/mfa/verify/",
                        {"code": code, "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.mfa_enabled)

    def test_an_account_with_nothing_to_prove_with_may_enrol_its_first_factor(self):
        """The escape hatch passkeys already have: an account provisioned
        through an identity provider has no password and no factor yet."""
        sso = make_user("sven", self.roles["Viewer"])
        sso.set_unusable_password()
        sso.save()
        r = self.client_for(sso).post("/api/auth/mfa/setup/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_an_sso_account_disables_with_a_backup_code(self):
        """M-6. Disabling insisted on ``check_password``, which is False for
        every account that signs in through an identity provider, so the
        factor could be added and never taken off."""
        sso = make_user("sonia", self.roles["Viewer"])
        sso.set_unusable_password()
        sso.save()
        client = self.client_for(sso)
        started = client.post("/api/auth/mfa/setup/", {}, format="json")
        from accounts import mfa as mfa_lib

        client.post("/api/auth/mfa/verify/",
                    {"code": mfa_lib.totp(started.data["secret"])}, format="json")
        sso.refresh_from_db()
        self.assertTrue(sso.mfa_enabled)
        codes = sso.issue_backup_codes()

        refused = client.post("/api/auth/mfa/disable/", {"password": "anything"}, format="json")
        self.assertEqual(refused.status_code, 403)

        allowed = client.post("/api/auth/mfa/disable/", {"otp": codes[0]}, format="json")
        self.assertEqual(allowed.status_code, 200, allowed.data)
        sso.refresh_from_db()
        self.assertFalse(sso.totp_enabled)

    def test_backup_codes_are_not_reissued_on_a_bare_session(self):
        client = self.client_for(self.owner)
        started = client.post("/api/auth/mfa/setup/", {"password": PASSWORD}, format="json")
        from accounts import mfa as mfa_lib

        client.post("/api/auth/mfa/verify/",
                    {"code": mfa_lib.totp(started.data["secret"]), "password": PASSWORD},
                    format="json")
        r = client.post("/api/auth/mfa/backup-codes/", {}, format="json")
        self.assertEqual(r.status_code, 403)


class SelfServiceEmailTests(APITestBase):
    """H-2. ``/users/me/`` wrote ``email`` with no verification and no
    uniqueness, and ``OIDC_LINK_BY_EMAIL`` (on by default) binds an identity
    provider's subject to whichever local account holds that address. Any
    signed-in account, the issued external auditor included, could claim an
    address whose owner had not signed in through SSO yet and take their
    first sign-in."""

    def test_a_user_cannot_set_their_own_email(self):
        before = self.viewer.email
        r = self.client_for(self.viewer).patch(
            "/api/users/me/", {"email": "cfo@example.com"}, format="json")
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.email, before)
        self.assertNotIn("cfo@example.com", str(r.data))

    def test_an_auditor_cannot_either(self):
        before = self.auditor.email
        self.client_for(self.auditor).patch(
            "/api/users/me/", {"email": "cfo@example.com"}, format="json")
        self.auditor.refresh_from_db()
        self.assertEqual(self.auditor.email, before)

    def test_the_rest_of_the_profile_still_saves(self):
        r = self.client_for(self.viewer).patch(
            "/api/users/me/", {"first_name": "Valerie", "job_title": "Analyst"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.first_name, "Valerie")
        self.assertEqual(self.viewer.job_title, "Analyst")

    def test_an_operator_cannot_duplicate_an_address(self):
        """Two accounts on one address is what makes an identity provider
        give up with ``ambiguous_email``, which is a denial of that person's
        sign-in rather than a takeover, but is still nobody's intent."""
        r = self.client_for(self.admin).post(
            "/api/users/", {"username": "newcomer", "email": self.owner.email,
                            "role": self.roles["Viewer"].pk}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)


class CrossTenantUniquenessTests(APITestBase):
    """M-3. The unscoped check was built scoped: the queryset carried
    ``workspace_id = ActiveWorkspace()``, which resolves at compile time, so
    running it inside ``unscoped()`` compared the column to NULL and matched
    nothing. The name then reached the database's global unique constraint
    and came back a 500, which is the disclosure the check was added to
    remove."""

    def setUp(self):
        super().setUp()
        self.beta = Workspace.objects.create(name="Beta", slug="beta")
        with tenancy.scoped(self.beta):
            self.stranger = make_user("beta-person", self.roles["Viewer"], workspace=self.beta)

    def test_a_name_taken_in_another_workspace_is_a_400_not_a_500(self):
        r = self.client_for(self.admin).post(
            "/api/users/", {"username": self.stranger.username, "email": "x@test.local",
                            "role": self.roles["Viewer"].pk}, format="json")
        self.assertEqual(r.status_code, 400, getattr(r, "data", r))
        self.assertIn("username", r.data)

    def test_the_refusal_does_not_say_where(self):
        r = self.client_for(self.admin).post(
            "/api/users/", {"username": self.stranger.username, "email": "x@test.local",
                            "role": self.roles["Viewer"].pk}, format="json")
        self.assertNotIn("beta", str(r.data).lower())

    def test_an_address_taken_in_another_workspace_is_allowed(self):
        """Deliberately unlike the username, which the database makes global.
        A consultant holds an account in two organisations on one
        installation under one address, and the only thing that breaks on a
        duplicate is an identity provider's lookup, which runs inside a
        single workspace."""
        r = self.client_for(self.admin).post(
            "/api/users/", {"username": "fresh", "email": self.stranger.email,
                            "role": self.roles["Viewer"].pk}, format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", r))

    def test_the_same_address_twice_in_one_workspace_is_refused(self):
        r = self.client_for(self.admin).post(
            "/api/users/", {"username": "fresher", "email": self.owner.email,
                            "role": self.roles["Viewer"].pk}, format="json")
        self.assertEqual(r.status_code, 400, getattr(r, "data", r))


@override_settings(AUTH_TRANSPORT="cookie")
class LoginCsrfTests(APITestBase):
    """M-5. ``_enforce_csrf`` runs inside ``CookieJWTAuthentication``, so it
    only ever saw a request that was already carrying a session. The two
    endpoints that *set* the cookies authenticate nobody, so a cross-site form
    post could sign the visitor's browser into the attacker's account, and
    the evidence they uploaded next went to it."""

    def setUp(self):
        super().setUp()
        # The test client sets ``_dont_enforce_csrf_checks``, which is what
        # Django's own check honours, so a client that does not opt in proves
        # nothing about CSRF either way.
        self.browser = APIClient(enforce_csrf_checks=True)

    def test_the_config_endpoint_seeds_the_token(self):
        r = self.browser.get("/api/auth/config/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(name.endswith("csrftoken") for name in r.cookies),
                        "nothing hands an anonymous visitor a CSRF token before login")

    def test_login_without_the_token_is_refused(self):
        r = self.browser.post("/api/auth/token/",
                              {"username": self.owner.username, "password": PASSWORD},
                              format="json")
        self.assertEqual(r.status_code, 403, getattr(r, "data", r))

    def test_login_with_the_token_still_works(self):
        seeded = self.browser.get("/api/auth/config/")
        token = [v.value for k, v in seeded.cookies.items() if k.endswith("csrftoken")][0]
        r = self.browser.post("/api/auth/token/",
                              {"username": self.owner.username, "password": PASSWORD},
                              format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))

    def test_the_refresh_endpoint_is_protected_too(self):
        seeded = self.browser.get("/api/auth/config/")
        token = [v.value for k, v in seeded.cookies.items() if k.endswith("csrftoken")][0]
        self.browser.post("/api/auth/token/",
                          {"username": self.owner.username, "password": PASSWORD},
                          format="json", HTTP_X_CSRFTOKEN=token)
        r = self.browser.post("/api/auth/token/refresh/", {}, format="json")
        self.assertEqual(r.status_code, 403, getattr(r, "data", r))

    def test_a_bearer_login_is_unaffected(self):
        with override_settings(AUTH_TRANSPORT="header"):
            r = self.browser.post("/api/auth/token/",
                                  {"username": self.owner.username, "password": PASSWORD},
                                  format="json")
            self.assertEqual(r.status_code, 200, getattr(r, "data", r))


class AccessTokenEpochTests(APITestBase):
    """M-4. "Signed out everywhere" walked ``OutstandingToken``, which holds
    refresh tokens only. The access token in the hijacked tab kept answering
    until it expired, up to an hour after the reset that was supposed to end
    it.

    Each revocation here happens through ``later()``. The stamp is floored to
    the second because the ``iat`` claim is whole seconds, and a stamp
    carrying microseconds would refuse the token the person signing in again
    has just been handed. That floor means a revocation in the same second as
    the token it revokes is a tie the token wins, which is a second-wide
    window in production and a coin toss in a test that does both in one
    breath. Moving the revocation on by a minute tests the rule rather than
    the clock.
    """

    @staticmethod
    def later(seconds=60):
        """Run the block as if it were ``seconds`` from now."""
        from django.utils import timezone

        moment = timezone.now() + timedelta(seconds=seconds)
        return mock.patch("django.utils.timezone.now", return_value=moment)

    def test_a_password_change_stops_the_access_token_it_was_issued_with(self):
        client = self.client_for(None)
        signed_in = client.post("/api/auth/token/",
                                {"username": self.owner.username, "password": PASSWORD},
                                format="json")
        access = signed_in.data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(client.get("/api/users/me/").status_code, 200)

        with self.later():
            self.client_for(self.owner).post(
                "/api/users/change_password/",
                {"current_password": PASSWORD, "new_password": "An0ther-Long-Passphrase!"},
                format="json")

        self.assertEqual(client.get("/api/users/me/").status_code, 401)

    def test_an_administrator_setting_a_password_does_the_same(self):
        client = self.client_for(None)
        signed_in = client.post("/api/auth/token/",
                                {"username": self.viewer.username, "password": PASSWORD},
                                format="json")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
        self.assertEqual(client.get("/api/users/me/").status_code, 200)

        with self.later():
            self.client_for(self.admin).patch(
                f"/api/users/{self.viewer.pk}/",
                {"password": "Administrator-Set-Passphrase!1"}, format="json")

        self.assertEqual(client.get("/api/users/me/").status_code, 401)

    def test_an_mfa_reset_does_the_same(self):
        client = self.client_for(None)
        signed_in = client.post("/api/auth/token/",
                                {"username": self.viewer.username, "password": PASSWORD},
                                format="json")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
        self.assertEqual(client.get("/api/users/me/").status_code, 200)

        with self.later():
            self.client_for(self.admin).post(
                f"/api/users/{self.viewer.pk}/reset_mfa/", {}, format="json")

        self.assertEqual(client.get("/api/users/me/").status_code, 401)

    def test_an_untouched_account_keeps_its_session(self):
        client = self.client_for(None)
        signed_in = client.post("/api/auth/token/",
                                {"username": self.owner.username, "password": PASSWORD},
                                format="json")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
        with self.later():
            self.client_for(self.admin).patch(
                f"/api/users/{self.viewer.pk}/", {"password": "Somebody-Elses-Passphrase!1"},
                format="json")
        self.assertEqual(client.get("/api/users/me/").status_code, 200)
