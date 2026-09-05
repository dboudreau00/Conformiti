"""
OIDC sign-in, fully offline: a local RSA key stands in for the provider and
``accounts.oidc._http`` is replaced with a fake that answers discovery, JWKS,
the token endpoint and userinfo.
"""
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from accounts.models import OidcIdentity, Role
from audit.models import AuditLog
from testutils import APITestBase

ISSUER = "https://idp.example"
CLIENT = "conformiti-web"
SETTINGS = dict(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID=CLIENT, OIDC_CLIENT_SECRET="s3cret",
                OIDC_LABEL="Sign in with Example", OIDC_ALLOWED_DOMAINS=[],
                OIDC_AUTO_PROVISION=False, OIDC_DEFAULT_ROLE="Viewer",
                OIDC_LINK_BY_EMAIL=True, OIDC_REQUIRE_VERIFIED_EMAIL=True, DEBUG=False)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key, kid):
    d = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    d.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return d


class FakeProvider:
    """Answers the four provider URLs. ``claims`` is what the next ID token
    carries; the fake fills iss/aud/iat/exp/nonce unless told not to."""

    def __init__(self):
        self.claims = {"sub": "sub-val", "email": "val@example.com", "email_verified": True,
                       "given_name": "Val", "family_name": "Viewer"}
        self.key, self.kid = _KEY, "k1"
        self.override = {}
        self.calls = []
        self.last_token_request = None
        self.userinfo = None

    def discovery(self):
        return {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/keys",
                "userinfo_endpoint": ISSUER + "/userinfo"}

    def id_token(self, nonce):
        now = int(time.time())
        payload = {"iss": ISSUER, "aud": CLIENT, "iat": now, "exp": now + 300, "nonce": nonce, **self.claims}
        payload.update(self.override)
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": self.kid})

    def __call__(self, url, data=None, headers=None):
        self.calls.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return self.discovery()
        if url.endswith("/keys"):
            return {"keys": [_jwk(_KEY, "k1")]}
        if url.endswith("/token"):
            self.last_token_request = parse_qs(data.decode("ascii"))
            nonce = self.last_token_request.get("nonce", [""])[0] or self._nonce
            return {"id_token": self.id_token(nonce), "access_token": "at-1", "token_type": "Bearer"}
        if url.endswith("/userinfo"):
            return self.userinfo or {}
        raise AssertionError(f"unexpected provider call {url}")


@override_settings(**SETTINGS)
class OidcFlowTests(APITestBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.idp = FakeProvider()
        self.patcher = mock.patch("accounts.oidc._http", side_effect=self.idp)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.viewer.email = "val@example.com"
        self.viewer.save()
        self.anon = self.client_class()

    def start(self):
        # Each flow is a fresh visitor as far as the per-IP login budget goes;
        # a single test walks the flow more times than the rate allows.
        cache.clear()
        r = self.anon.get("/api/auth/oidc/start/")
        self.assertEqual(r.status_code, 302, getattr(r, "url", ""))
        q = parse_qs(urlparse(r["Location"]).query)
        self.idp._nonce = q["nonce"][0]
        return q

    def callback(self, state, code="code-1", **extra):
        return self.anon.get("/api/auth/oidc/callback/", {"code": code, "state": state, **extra})

    def sign_in(self):
        q = self.start()
        r = self.callback(q["state"][0])
        self.assertEqual(r.status_code, 302)
        target = urlparse(r["Location"])
        self.assertEqual(target.path, "/login")
        params = parse_qs(target.query)
        self.assertNotIn("sso_error", params, params)
        return params["sso"][0]

    # ---------------------------------------------------------------- start
    def test_start_sends_pkce_state_and_nonce_and_parks_them_in_the_session(self):
        q = self.start()
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["client_id"], [CLIENT])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["scope"], ["openid email profile"])
        self.assertTrue(q["redirect_uri"][0].endswith("/api/auth/oidc/callback/"))
        flow = self.anon.session["oidc_flow"]
        self.assertEqual(flow["state"], q["state"][0])
        self.assertEqual(flow["nonce"], q["nonce"][0])
        self.assertTrue(flow["verifier"])

    def test_config_advertises_the_button(self):
        r = self.anon.get("/api/auth/config/")
        self.assertEqual(r.data["oidc"], {"enabled": True, "label": "Sign in with Example"})
        with override_settings(OIDC_CLIENT_SECRET=""):
            self.assertFalse(self.anon.get("/api/auth/config/").data["oidc"]["enabled"])
            r = self.anon.get("/api/auth/oidc/start/")
            self.assertEqual(r["Location"], "/login?sso_error=disabled")

    # ------------------------------------------------------------ happy path
    def test_a_verified_email_links_an_existing_account_and_signs_it_in(self):
        ticket = self.sign_in()
        self.assertEqual(self.idp.last_token_request["grant_type"], ["authorization_code"])
        self.assertTrue(self.idp.last_token_request["code_verifier"][0])
        identity = OidcIdentity.objects.get(issuer=ISSUER, subject="sub-val")
        self.assertEqual(identity.user, self.viewer)
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        me = self.anon.get("/api/users/me/", HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        self.assertEqual(me.data["username"], "val")
        row = AuditLog.objects.filter(action="login", user=self.viewer).latest("timestamp")
        self.assertIn("sso sign-in (linked by verified email)", row.detail)

    def test_a_linked_identity_is_used_even_when_the_email_changes(self):
        OidcIdentity.objects.create(user=self.owner, issuer=ISSUER, subject="sub-val", email="old@example.com")
        self.idp.claims["email"] = "val@example.com"     # would match val, but sub is owen's
        ticket = self.sign_in()
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        me = self.anon.get("/api/users/me/", HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        self.assertEqual(me.data["username"], "owen")
        self.assertEqual(OidcIdentity.objects.get(subject="sub-val").email, "val@example.com")

    def test_email_missing_from_the_id_token_is_fetched_from_userinfo(self):
        self.idp.claims.pop("email")
        self.idp.claims.pop("email_verified")
        self.idp.userinfo = {"sub": "sub-val", "email": "val@example.com", "email_verified": True}
        self.sign_in()
        self.assertTrue(OidcIdentity.objects.filter(user=self.viewer).exists())
        # A userinfo answer about someone else is ignored.
        OidcIdentity.objects.all().delete()
        self.idp.userinfo = {"sub": "somebody-else", "email": "val@example.com", "email_verified": True}
        q = self.start()
        r = self.callback(q["state"][0])
        self.assertIn("sso_error=no_email", r["Location"])

    # ------------------------------------------------------------ refusals
    def _refused(self, code):
        q = self.start()
        r = self.callback(q["state"][0])
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"sso_error={code}", r["Location"])
        self.assertTrue(AuditLog.objects.filter(action="login_failed", detail__contains=f"({code})").exists())

    def test_privileged_accounts_are_never_linked_by_email(self):
        self.admin.email = "ada@example.com"
        self.admin.save()
        self.idp.claims.update({"sub": "sub-ada", "email": "ada@example.com"})
        self._refused("privileged")
        self.assertFalse(OidcIdentity.objects.exists())
        # ...but a deliberate CLI link is honoured.
        with self.assertRaises(CommandError):
            call_command("link_oidc_identity", "ada", "sub-ada")
        call_command("link_oidc_identity", "ada", "sub-ada", "--allow-privileged")
        self.assertEqual(OidcIdentity.objects.get(subject="sub-ada").user, self.admin)
        ticket = self.sign_in()
        self.assertTrue(ticket)

    def test_domain_allow_list(self):
        with override_settings(OIDC_ALLOWED_DOMAINS=["corp.example"]):
            self._refused("domain")
            self.idp.claims.update({"sub": "sub-new", "email": "new@corp.example"})
            with override_settings(OIDC_AUTO_PROVISION=True):
                self.sign_in()
        user = OidcIdentity.objects.get(subject="sub-new").user
        self.assertEqual(user.email, "new@corp.example")
        self.assertEqual(user.role.name, "Viewer")
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual((user.first_name, user.last_name), ("Val", "Viewer"))

    def test_unknown_identity_without_provisioning_is_declined(self):
        self.idp.claims.update({"sub": "sub-x", "email": "nobody@example.com"})
        self._refused("unknown_user")

    def test_provisioning_refuses_a_role_that_manages_users(self):
        self.idp.claims.update({"sub": "sub-x", "email": "nobody@example.com"})
        with override_settings(OIDC_AUTO_PROVISION=True, OIDC_DEFAULT_ROLE="Administrator"):
            self.assertTrue(Role.objects.get(name="Administrator").can_manage_users)
            self._refused("role")
        with override_settings(OIDC_AUTO_PROVISION=True, OIDC_DEFAULT_ROLE="No Such Role"):
            self._refused("role")

    def test_unverified_email_and_missing_email(self):
        self.idp.claims["email_verified"] = False
        self._refused("unverified_email")
        with override_settings(OIDC_REQUIRE_VERIFIED_EMAIL=False):
            self.sign_in()

    def test_ambiguous_email(self):
        self.owner.email = "val@example.com"
        self.owner.save()
        self._refused("ambiguous_email")

    def test_inactive_accounts_cannot_sign_in(self):
        self.viewer.is_active = False
        self.viewer.save()
        self._refused("inactive")

    def test_the_provider_declining_is_reported(self):
        q = self.start()
        r = self.callback(q["state"][0], error="access_denied", error_description="User cancelled")
        self.assertIn("sso_error=denied", r["Location"])

    # -------------------------------------------------------- token checks
    def test_state_mismatch_and_replay(self):
        self.start()
        r = self.callback("not-the-state")
        self.assertIn("sso_error=state", r["Location"])
        # The flow was consumed: the real state no longer works either.
        q = self.start()
        self.callback(q["state"][0])
        r = self.callback(q["state"][0])
        self.assertIn("sso_error=state", r["Location"])

    def test_bad_nonce_wrong_audience_expiry_and_unknown_key_are_rejected(self):
        for override in ({"nonce": "stale"}, {"aud": "someone-else"}, {"exp": int(time.time()) - 600},
                         {"iss": "https://evil.example"}):
            self.idp.override = override
            self._refused("token")
        self.idp.override = {}
        self.idp.key, self.idp.kid = _OTHER_KEY, "k1"        # same kid, different key
        self._refused("token")
        self.idp.kid = "unknown-kid"
        self._refused("token")

    def test_symmetric_alg_is_refused(self):
        self.start()
        raw = jwt.encode({"iss": ISSUER, "aud": CLIENT, "sub": "sub-val", "iat": 1, "exp": 2 ** 31},
                         "s3cret", algorithm="HS256")
        from accounts import oidc
        with self.assertRaises(oidc.OidcError) as ctx:
            oidc.verify_id_token(oidc.config(), self.idp.discovery(), raw, "n")
        self.assertEqual(ctx.exception.code, "token")

    # ---------------------------------------------------------- tickets
    def test_tickets_are_single_use_and_bound_to_the_browser_session(self):
        ticket = self.sign_in()
        # Lifted out of the redirect URL into another browser: useless there,
        # and the attempt does not spend it for the browser that earned it.
        other = self.client_class()
        r = other.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "state")
        self.assertEqual(self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").status_code, 200)
        self.assertEqual(self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").status_code, 400)
        # The wrong ticket in the right session is refused and spends the real one.
        ticket = self.sign_in()
        self.assertEqual(self.anon.post("/api/auth/oidc/redeem/", {"ticket": "guess"}, format="json").status_code, 400)
        self.assertEqual(self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").status_code, 400)

    def test_a_trailing_slash_issuer_still_matches(self):
        """Auth0 and Entra v1 publish the issuer with a trailing slash."""
        self.idp.override = {"iss": ISSUER + "/"}
        with override_settings(OIDC_ISSUER=ISSUER + "/"):
            self.assertTrue(self.sign_in())

    def test_the_administrator_role_is_never_linked_by_email(self):
        self.viewer.role = Role.objects.get(name="Administrator")
        self.viewer.save()
        self._refused("privileged")
        self.assertFalse(OidcIdentity.objects.exists())

    def test_a_linked_user_promoted_later_loses_sso_until_reaffirmed(self):
        self.sign_in()
        self.viewer.is_staff = True
        self.viewer.save()
        self._refused("privileged")
        call_command("link_oidc_identity", "val", "sub-val", "--allow-privileged")
        self.assertTrue(self.sign_in())

    def test_step_up_follows_the_amr_claim(self):
        from accounts import mfa as mfa_lib
        from accounts.models import MfaDevice

        secret = mfa_lib.generate_secret()
        MfaDevice.objects.create(user=self.viewer, secret=secret, enabled=True)
        # No second factor asserted: the local authenticator is asked for.
        self.idp.claims["amr"] = ["pwd"]
        ticket = self.sign_in()
        self.assertEqual(self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").data,
                         {"mfa_required": True})
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket, "otp": mfa_lib.totp(secret)}, format="json")
        self.assertIn("access", r.data)
        # The provider asserted MFA: straight in.
        self.idp.claims["amr"] = ["pwd", "mfa"]
        ticket = self.sign_in()
        self.assertIn("access", self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").data)

    def test_non_ascii_state_is_a_clean_refusal(self):
        self.start()
        r = self.callback("état-☃")
        self.assertEqual(r.status_code, 302)
        self.assertIn("sso_error=state", r["Location"])

    @override_settings(AUTH_TRANSPORT="cookie")
    def test_cookie_mode_hands_the_tokens_out_as_cookies(self):
        ticket = self.sign_in()
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data, {"authenticated": True})
        self.assertIn("conformiti_access", r.cookies)
        self.assertTrue(r.cookies["conformiti_access"]["httponly"])
        me = self.anon.get("/api/users/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["username"], "val")

    def test_next_path_must_be_local(self):
        r = self.anon.get("/api/auth/oidc/start/", {"next": "https://evil.example/"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.anon.session["oidc_flow"]["next"], "/")
        r = self.anon.get("/api/auth/oidc/start/", {"next": "/vendors?vendor=3"})
        self.assertEqual(self.anon.session["oidc_flow"]["next"], "/vendors?vendor=3")


class OidcConfigGuardTests(APITestBase):
    def test_discovery_must_name_the_configured_issuer(self):
        from accounts import oidc

        with override_settings(**SETTINGS), mock.patch(
                "accounts.oidc._http", return_value={"issuer": "https://other.example",
                                                     "authorization_endpoint": "x", "token_endpoint": "y",
                                                     "jwks_uri": "z"}):
            cache.clear()
            with self.assertRaises(oidc.OidcError) as ctx:
                oidc.discovery(oidc.config())
            self.assertEqual(ctx.exception.code, "provider")

    def test_plain_http_providers_are_refused_outside_debug(self):
        from accounts import oidc

        with override_settings(DEBUG=False):
            with self.assertRaises(oidc.OidcError) as ctx:
                oidc._http("http://idp.example/.well-known/openid-configuration")
            self.assertEqual(ctx.exception.code, "provider")

    def test_unlink_command(self):
        OidcIdentity.objects.create(user=self.viewer, issuer=ISSUER, subject="s")
        call_command("link_oidc_identity", "val", "--unlink")
        self.assertFalse(OidcIdentity.objects.exists())
