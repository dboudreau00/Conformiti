"""Findings H-1, H-2 and M-3 to M-6 of the fourth independent review. H-3 is held by the image workflow and
``tools/validate.py``, M-1 by ``tests_auditor_surface`` and M-2 by ``documents.tests_uploads``."""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from accounts import tenancy
from accounts.models import Workspace
from testutils import PASSWORD, APITestBase, make_user


class ReauthOnEveryFactorChangeTests(APITestBase):
    """H-1 and M-6. Adding a passkey or an authenticator app asks the caller to prove the account is theirs: a stolen
    session could otherwise enrol its own app and lock the owner out."""

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
        """As for passkeys: an account provisioned through an identity provider has no password and no factor yet."""
        sso = make_user("sven", self.roles["Viewer"])
        sso.set_unusable_password()
        sso.save()
        r = self.client_for(sso).post("/api/auth/mfa/setup/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_an_sso_account_disables_with_a_backup_code(self):
        """M-6. Disabling must not depend on ``check_password``, which is False for every SSO account: the factor could
        otherwise be added and never removed."""
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
    """H-2. ``OIDC_LINK_BY_EMAIL`` binds an identity provider's subject to the account holding the asserted address,
    so ``/users/me/`` must refuse an ``email`` edit: it would let anyone claim a colleague's first SSO sign-in."""

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
        """Two accounts on one address make an identity provider give up (``ambiguous_email``) and lock one out."""
        r = self.client_for(self.admin).post(
            "/api/users/", {"username": "newcomer", "email": self.owner.email,
                            "role": self.roles["Viewer"].pk}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.data)


class CrossTenantUniquenessTests(APITestBase):
    """M-3. The unscoped username check must build its queryset inside the unscoped block, or ``ActiveWorkspace()``
    compares to NULL, nothing matches and the unique constraint answers 500, which discloses the account."""

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
        """Unlike the username, which the database makes global: a consultant may hold an account in two organisations
        under one address; a duplicate only breaks an identity provider's lookup, which runs inside one workspace."""
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
    """M-5. The two endpoints that set the cookies authenticate nobody, so ``_enforce_csrf`` never sees them and they
    must check CSRF themselves, or a cross-site form post could sign the visitor into the attacker's account."""

    def setUp(self):
        super().setUp()
        # The test client sets ``_dont_enforce_csrf_checks``, so only a client that opts in proves anything about CSRF.
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
    """M-4. Revoking ``OutstandingToken`` rows reaches refresh tokens only, so an access token is also refused on its
    issue time. ``later()`` moves the revocation a minute on, because the stamp is floored to the second."""

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

    def test_signing_out_of_one_browser_leaves_the_others_alone(self):
        """Ending every session is for the recovery paths, not for sign-out: refusing the access token another browser
        holds would close the person's other device mid-session."""
        phone = self.client_for(None)
        signed_in = phone.post("/api/auth/token/",
                               {"username": self.owner.username, "password": PASSWORD},
                               format="json")
        phone.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
        self.assertEqual(phone.get("/api/users/me/").status_code, 200)

        with self.later():
            laptop = self.client_for(None)
            other = laptop.post("/api/auth/token/",
                                {"username": self.owner.username, "password": PASSWORD},
                                format="json")
            laptop.credentials(HTTP_AUTHORIZATION=f"Bearer {other.data['access']}")
            laptop.post("/api/auth/token/clear/", {"refresh": other.data["refresh"]},
                        format="json")

        self.assertEqual(phone.get("/api/users/me/").status_code, 200,
                         "signing out of one browser must not close the other")

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
