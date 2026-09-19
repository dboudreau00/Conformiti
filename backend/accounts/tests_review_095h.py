"""The fifth independent review, fixed in 0.9.5h.

M-1 the password login minted a refresh token before the second factor ·
M-3 an auditor role could also hold capabilities, and the capability
short-circuits ran above the auditor cap · M-4 the production topology put
every caller in one throttle bucket · M-5 a site-local IPv6 address read as
public, and an IP literal went unchecked under a proxy · M-6 a client could
make ``request.is_secure()`` true on the plain-HTTP stack · L-2 signing out
was the one cookie endpoint with no CSRF check · L-7 leading whitespace hid a
formula from the CSV guard.

M-2 lives in ``attestations.tests_pbc`` beside the list it changes, L-1 in
``attestations.tests_review_fixes``, L-5 in ``documents.tests``, and L-6 in
``vendors.tests_questionnaire``. L-3 is a shell script and L-8 is deferred;
REVIEW_095H.md says why.
"""
from datetime import timedelta
from unittest import mock

from django.test import override_settings

from accounts.models import Role
from config import outbound
from config.csvsafe import csv_safe
from testutils import PASSWORD, APITestBase, make_user


class LoginMintsAfterTheFactorTests(APITestBase):
    """M-1. ``TokenObtainPairSerializer.validate`` authenticates and mints in
    one call, so calling it before the MFA branch left a refresh token in
    OutstandingToken, and moved last_login, for a session no second factor had
    authorised. The browser never saw it; a database dump, a replica and the
    admin do, and a signed JWT needs no key ring to use."""

    def setUp(self):
        super().setUp()
        self.person = make_user("mfa-person", self.roles["Viewer"])
        client = self.client_for(self.person)
        started = client.post("/api/auth/mfa/setup/", {"password": PASSWORD}, format="json")
        from accounts import mfa as mfa_lib

        client.post("/api/auth/mfa/verify/",
                    {"code": mfa_lib.totp(started.data["secret"]), "password": PASSWORD},
                    format="json")
        self.person.refresh_from_db()
        self.assertTrue(self.person.mfa_enabled)
        self._forget_tokens()

    def _forget_tokens(self):
        """Enrolment itself signs in nothing, but the setUp above used the
        API; start the count from zero so the assertions below are about the
        login under test."""
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        OutstandingToken.objects.filter(user=self.person).delete()

    def outstanding(self):
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

        return OutstandingToken.objects.filter(user=self.person).count()

    def test_the_challenge_mints_nothing(self):
        before = self.person.last_login
        r = self.client_for(None).post(
            "/api/auth/token/", {"username": self.person.username, "password": PASSWORD},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data.get("mfa_required"))
        self.assertEqual(self.outstanding(), 0,
                         "a refresh token exists for a session no factor authorised")
        self.person.refresh_from_db()
        self.assertEqual(self.person.last_login, before)

    def test_a_wrong_code_mints_nothing(self):
        r = self.client_for(None).post(
            "/api/auth/token/",
            {"username": self.person.username, "password": PASSWORD, "otp": "000000"},
            format="json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.outstanding(), 0)

    def test_a_completed_login_still_mints_exactly_one(self):
        """The positive control. Without it the assertions above would pass
        just as well if minting had broken altogether.

        A backup code rather than a fresh TOTP: enrolling spent this time
        step deliberately, so the code that switched the factor on cannot
        then sign in with it."""
        codes = self.person.issue_backup_codes()
        r = self.client_for(None).post(
            "/api/auth/token/",
            {"username": self.person.username, "password": PASSWORD, "otp": codes[0]},
            format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        self.assertIn("access", r.data)
        self.assertEqual(self.outstanding(), 1)
        self.person.refresh_from_db()
        self.assertIsNotNone(self.person.last_login)

    def test_an_account_with_no_second_factor_is_unaffected(self):
        r = self.client_for(None).post(
            "/api/auth/token/", {"username": self.viewer.username, "password": PASSWORD},
            format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))


class AuditorRoleHoldsNoCapabilitiesTests(APITestBase):
    """M-3. The shipped Auditor role is ``is_auditor`` alone and is locked, but
    a custom role was not: any combination stored, and ``PackageGrant`` only
    asks for ``is_auditor``. Such an account could be issued an engagement and
    then read every folder and every package, because the capability
    short-circuits in both access modules sit above the auditor cap."""

    def setUp(self):
        super().setUp()
        self.mixed = Role.objects.create(name="Field auditor", is_auditor=True,
                                         can_view_all=True, can_manage_folders=True)
        self.person = make_user("field-auditor", self.mixed)

    def test_a_capability_is_refused_to_an_auditor_role(self):
        self.assertFalse(self.person.can_view_all)
        self.assertFalse(self.person.can_manage_folders)
        self.assertFalse(self.person.can_manage_frameworks)
        self.assertTrue(self.person.is_auditor, "the role still identifies as an auditor")

    def test_the_stored_flags_are_untouched(self):
        """No data migration: the row keeps what an operator configured, and
        the cap is applied when it is read."""
        self.mixed.refresh_from_db()
        self.assertTrue(self.mixed.can_view_all)

    def test_the_folder_tree_is_not_the_whole_tree(self):
        from documents.access import accessible_folder_ids
        from documents.models import Folder

        self.assertNotEqual(accessible_folder_ids(self.person),
                            set(Folder.objects.values_list("id", flat=True)))
        self.assertEqual(accessible_folder_ids(self.person), set())

    def test_no_package_is_readable_without_a_grant(self):
        from attestations.access import readable_packages

        self.assertEqual(readable_packages(self.person).count(), 0)

    def test_the_capabilities_payload_reports_the_capped_view(self):
        """What the interface uses to decide which buttons exist."""
        r = self.client_for(self.person).get("/api/users/me/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["capabilities"]["view_all"])
        self.assertTrue(r.data["capabilities"]["auditor"])

    def test_a_new_mixed_role_is_refused(self):
        r = self.client_for(self.admin).post(
            "/api/roles/", {"name": "Outside reviewer", "is_auditor": True,
                            "can_view_all": True}, format="json")
        self.assertEqual(r.status_code, 400, getattr(r, "data", r))
        self.assertIn("is_auditor", r.data)

    def test_adding_a_capability_to_an_auditor_role_is_refused(self):
        plain = Role.objects.create(name="Outside reviewer", is_auditor=True)
        r = self.client_for(self.admin).patch(
            f"/api/roles/{plain.pk}/", {"can_view_all": True}, format="json")
        self.assertEqual(r.status_code, 400, getattr(r, "data", r))

    def test_making_a_capable_role_an_auditor_is_refused(self):
        staff = Role.objects.create(name="Reviewer", can_view_all=True)
        r = self.client_for(self.admin).patch(
            f"/api/roles/{staff.pk}/", {"is_auditor": True}, format="json")
        self.assertEqual(r.status_code, 400, getattr(r, "data", r))

    def test_renaming_a_role_that_already_holds_both_still_works(self):
        """The refusal is about introducing the combination. Refusing to save
        a legacy row at all would be the silent strip this release
        deliberately does not do."""
        r = self.client_for(self.admin).patch(
            f"/api/roles/{self.mixed.pk}/", {"description": "Historic"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))


class ForwardedProtoTests(APITestBase):
    """M-6. ``SECURE_PROXY_SSL_HEADER`` was set whenever DEBUG was off, which
    includes the shipped compose stack, where nginx listens on plain HTTP and
    BEHIND_TLS is false. Any client could then assert it was on https, and
    ``build_absolute_uri`` emitted an OIDC redirect_uri and a SAML ACS at an
    address they were never registered at."""

    HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    @override_settings(SECURE_PROXY_SSL_HEADER=None)
    def test_the_header_is_ignored_when_no_terminator_was_declared(self):
        r = self.client_for(self.viewer).get("/api/users/me/", **{self.HEADER[0]: "https"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.wsgi_request.is_secure())

    @override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
    def test_the_header_is_honoured_once_one_is(self):
        r = self.client_for(self.viewer).get("/api/users/me/", **{self.HEADER[0]: "https"})
        self.assertTrue(r.wsgi_request.is_secure())

    def test_the_setting_follows_behind_tls_not_debug(self):
        """The shipped image pins DEBUG off and BEHIND_TLS false, which is the
        combination that used to trust the client."""
        import importlib

        with mock.patch.dict("os.environ", {"DJANGO_DEBUG": "false", "BEHIND_TLS": "false"}):
            module = importlib.import_module("config.settings")
            source = open(module.__file__, encoding="utf-8").read()
        self.assertIn("if BEHIND_TLS:\n", source)
        self.assertNotIn('if not DEBUG:\n    # We sit behind nginx', source)


class OutboundAddressTests(APITestBase):
    """M-5. ``fec0::/10`` is deprecated site-local unicast that Python reports
    as global, so every rule in ``ip_is_public`` missed it, and the Jira base
    URL is set by anyone who can manage users with no host allow-list."""

    def test_site_local_ipv6_is_not_public(self):
        self.assertFalse(outbound.ip_is_public("fec0::1"))

    def test_the_ranges_that_already_worked_still_do(self):
        for address in ("fc00::1", "fe80::1", "::ffff:100.64.0.1", "10.0.0.1", "169.254.169.254"):
            with self.subTest(address=address):
                self.assertFalse(outbound.ip_is_public(address))
        for address in ("93.184.216.34", "2606:4700::1"):
            with self.subTest(address=address):
                self.assertTrue(outbound.ip_is_public(address))

    def test_a_site_local_url_is_refused(self):
        with self.assertRaises(outbound.OutboundError):
            outbound.assert_safe_url("https://[fec0::1]/")

    def test_a_literal_is_checked_even_when_a_proxy_applies(self):
        """A proxy resolves names; it does not change what a literal is. The
        early return skipped the check entirely whenever one was configured."""
        with mock.patch.object(outbound, "proxy_for", return_value="http://proxy.internal:3128"):
            with self.assertRaises(outbound.OutboundError):
                outbound.assert_safe_url("https://169.254.169.254/")
            with self.assertRaises(outbound.OutboundError):
                outbound.assert_safe_url("https://[fec0::1]/")

    def test_a_public_host_still_goes_through_the_proxy_unresolved(self):
        with mock.patch.object(outbound, "proxy_for", return_value="http://proxy.internal:3128"):
            self.assertIsNone(outbound.assert_safe_url("https://hooks.slack.com/services/T/B/x"))


@override_settings(AUTH_TRANSPORT="cookie")
class SignOutCsrfTests(APITestBase):
    """L-2. 0.9.5f put the check on the three endpoints that set the auth
    cookies and missed the one that clears them, which is the endpoint whose
    whole purpose is the case where the access cookie is gone and the refresh
    cookie is not, so the check inside cookie authentication never runs."""

    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient

        self.browser = APIClient(enforce_csrf_checks=True)

    def test_clearing_without_a_token_is_refused(self):
        r = self.browser.post("/api/auth/token/clear/", {}, format="json")
        self.assertEqual(r.status_code, 403, getattr(r, "data", r))

    def test_clearing_with_the_token_still_works(self):
        seeded = self.browser.get("/api/auth/config/")
        token = [v.value for k, v in seeded.cookies.items() if k.endswith("csrftoken")][0]
        r = self.browser.post("/api/auth/token/clear/", {}, format="json",
                              HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))

    def test_a_bearer_client_is_unaffected(self):
        with override_settings(AUTH_TRANSPORT="header"):
            r = self.browser.post("/api/auth/token/clear/", {}, format="json")
            self.assertEqual(r.status_code, 200, getattr(r, "data", r))


class CsvFormulaTests(APITestBase):
    """L-7. The guard read the first character of the raw value. Excel ignores
    leading whitespace when it decides whether a cell is a formula."""

    def test_leading_whitespace_does_not_hide_a_formula(self):
        for value in ("\n=cmd", " =1+1", "\t@SUM(A1)", "  -2+3"):
            with self.subTest(value=value):
                self.assertTrue(csv_safe([value])[0].startswith("'"), value)

    def test_ordinary_values_are_untouched(self):
        for value in ("Quarterly review", "", "  indented note", "2026-01-01"):
            with self.subTest(value=value):
                self.assertEqual(csv_safe([value])[0], value)

    def test_the_value_itself_is_not_trimmed(self):
        """An export is evidence. The prefix is added; nothing else changes."""
        self.assertEqual(csv_safe([" =1+1"])[0], "' =1+1")


class ThrottleDepthTests(APITestBase):
    """M-4. NUM_PROXIES is the number of hops DRF walks back along
    X-Forwarded-For to find the client. The default of 1 is the shipped nginx;
    the production section of INSTALL.md puts a TLS terminator in front of
    that without mentioning it, and at 1 every visitor then shares the
    terminator's address, so one caller spends the login budget for all of
    them."""

    def test_the_production_checklist_names_it(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        install = (root / "INSTALL.md").read_text(encoding="utf-8")
        production = install[install.index("### Going to production"):]
        production = production[:production.index("### Single sign-on")]
        self.assertIn("NUM_PROXIES", production,
                      "the step that puts TLS in front must say what it does to the throttles")

    def test_the_example_env_explains_the_second_hop(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        example = (root / ".env.example").read_text(encoding="utf-8")
        self.assertIn("NUM_PROXIES=2", example)


class DeferredTests(APITestBase):
    """L-8 is deferred, and the workaround it rests on has to keep working.

    Reauth takes a password, a TOTP code or a backup code, not a passkey
    assertion, so an SSO account whose only factor is a passkey needs its
    backup codes. Enrolling the first passkey issues them; if that ever
    stopped being true, the deferral would become a lockout."""

    def test_enrolling_a_first_passkey_issues_backup_codes(self):
        from accounts.models import WebAuthnCredential

        sso = make_user("passkey-only", self.roles["Viewer"])
        sso.set_unusable_password()
        sso.save()
        self.assertEqual(sso.backup_codes_remaining, 0)
        WebAuthnCredential.objects.create(
            user=sso, credential_id="x" * 16, public_key=b"y" * 16,
            algorithm=-7, name="Only key")
        codes = sso.issue_backup_codes()
        self.assertEqual(len(codes), 10)
        self.assertTrue(sso.verify_backup_code(codes[0]))
