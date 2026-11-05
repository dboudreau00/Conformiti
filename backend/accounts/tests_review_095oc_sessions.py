"""0.9.5oc session fixes: TEN-02 (an admin session no longer pins the token user's lookup), AUTH-01 (a tolerant renewal
endpoint inside the refresh cookie's path) and WEB-02 (a sign-out that arrives with only a refresh token is audited)."""
from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import cookie_auth
from accounts.models import Workspace
from audit.models import AuditLog
from testutils import PASSWORD, APITestBase, make_user


class AdminSessionDoesNotPinTheTokenUserTests(APITestBase):
    """TEN-02. Django's session user decides the workspace the request resolves to, which scoped the lookup of the
    user named by the token: a superuser with the admin open who switched workspace got 401 'User not found'."""

    def setUp(self):
        super().setUp()
        self.acme = Workspace.objects.create(name="Acme", slug="acme")

    def browser(self, session_user, token_user, workspace=None):
        client = APIClient()
        client.force_login(session_user)
        extra = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(token_user).access_token}"}
        if workspace:
            extra["HTTP_X_WORKSPACE"] = workspace
        client.credentials(**extra)
        return client

    def test_a_superuser_with_the_admin_session_open_can_switch_workspace(self):
        r = self.browser(self.admin, self.admin, workspace="acme").get("/api/users/me/")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        self.assertEqual(r.data["username"], self.admin.username)
        # The switch took effect: Acme has no users, Default has five.
        listing = self.browser(self.admin, self.admin, workspace="acme").get("/api/users/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 0)
        home = self.browser(self.admin, self.admin).get("/api/users/")
        self.assertEqual(home.data["count"], 5)

    def test_a_session_for_another_workspace_does_not_hide_the_token_user(self):
        zed = make_user("zed", self.roles["Compliance Manager"], workspace=self.acme)
        r = self.browser(self.viewer, zed).get("/api/users/me/")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        self.assertEqual(r.data["username"], "zed")

    def test_the_session_user_cannot_lend_its_workspace_header_to_a_member(self):
        zed = make_user("zed", self.roles["Compliance Manager"], workspace=self.acme)
        # Even with the admin session and a header naming Default, a non-superuser stays in their own workspace.
        r = self.browser(self.admin, zed, workspace="default").get("/api/users/")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        self.assertEqual([u["username"] for u in r.data["results"]], ["zed"])

    def test_a_deleted_account_is_still_refused(self):
        zed = make_user("zed", self.roles["Compliance Manager"], workspace=self.acme)
        token = RefreshToken.for_user(zed).access_token
        zed.delete()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/users/me/").status_code, 401)


@override_settings(AUTH_TRANSPORT="cookie")
class CookieModeRenewalTests(APITestBase):
    """AUTH-01. The refresh cookie travels only under ``AUTH_COOKIE_REFRESH_PATH``, so the cold-load renewal lives
    there. Django's test client sends every cookie whatever its path, so the path itself is asserted."""

    URL = "/api/auth/token/renew/"

    def setUp(self):
        super().setUp()
        self.browser = APIClient(enforce_csrf_checks=True)

    def sign_in(self):
        self.browser.get("/api/auth/config/")
        csrf = self.csrf()
        r = self.browser.post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json",
                              HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        return r

    def csrf(self):
        return [v.value for k, v in self.browser.cookies.items() if k.endswith("csrftoken")][0]

    def test_the_endpoint_is_inside_the_refresh_cookie_path(self):
        self.assertTrue(self.URL.startswith(settings.AUTH_COOKIE_REFRESH_PATH))

    def test_a_dead_access_cookie_with_a_live_refresh_cookie_is_renewed(self):
        first = self.sign_in().cookies[cookie_auth.refresh_cookie_name()].value
        self.browser.cookies.pop(cookie_auth.access_cookie_name())
        r = self.browser.post(self.URL, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        self.assertEqual(r.data, {"renewed": True})
        self.assertTrue(r.cookies[cookie_auth.access_cookie_name()].value)
        self.assertNotEqual(r.cookies[cookie_auth.refresh_cookie_name()].value, first, "the refresh token rotates")
        me = self.browser.get("/api/users/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["username"], "mia")

    def test_a_visitor_with_no_refresh_cookie_gets_a_quiet_no(self):
        self.browser.get("/api/auth/config/")
        r = self.browser.post(self.URL, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf())
        self.assertEqual(r.status_code, 200, "an anonymous cold load must not log a console error")
        self.assertEqual(r.data, {"renewed": False})
        self.assertNotIn(cookie_auth.access_cookie_name(), r.cookies)

    def test_a_dead_refresh_token_is_a_quiet_no_and_leaves_the_cookies_alone(self):
        self.sign_in()
        refresh = self.browser.cookies[cookie_auth.refresh_cookie_name()].value
        csrf = self.csrf()
        RefreshToken(refresh).blacklist()
        r = self.browser.post(self.URL, {}, format="json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"renewed": False})
        # Not expired by this response: two tabs racing for the same token must not clear the winner's new cookies.
        self.assertEqual(len(r.cookies), 0)

    def test_an_account_switched_off_or_deleted_since_is_a_quiet_no(self):
        # The cookie still verifies after either; the renewal must answer no, never 401 or 500.
        for leave in ("deactivate", "delete"):
            with self.subTest(leave):
                person = make_user(f"leaver-{leave}", self.roles["Viewer"])
                self.browser = APIClient(enforce_csrf_checks=True)
                self.browser.get("/api/auth/config/")
                r = self.browser.post("/api/auth/token/", {"username": person.username, "password": PASSWORD},
                                      format="json", HTTP_X_CSRFTOKEN=self.csrf())
                self.assertEqual(r.status_code, 200, getattr(r, "data", r))
                self.browser.cookies.pop(cookie_auth.access_cookie_name())
                if leave == "delete":
                    person.delete()
                else:
                    type(person).objects.filter(pk=person.pk).update(is_active=False)
                r = self.browser.post(self.URL, {}, format="json", HTTP_X_CSRFTOKEN=self.csrf())
                self.assertEqual(r.status_code, 200, getattr(r, "data", r))
                self.assertEqual(r.data, {"renewed": False})

    def test_the_renewal_is_csrf_checked(self):
        self.sign_in()
        self.browser.cookies.pop(cookie_auth.access_cookie_name())
        self.assertEqual(self.browser.post(self.URL, {}, format="json").status_code, 403)

    def test_a_visitor_without_a_refresh_cookie_is_not_throttled_but_one_with_a_cookie_is(self):
        from unittest import mock

        from rest_framework.throttling import SimpleRateThrottle

        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"refresh": "2/min"}):
            self.browser.get("/api/auth/config/")
            csrf = self.csrf()
            for _ in range(5):
                r = self.browser.post(self.URL, {}, format="json", HTTP_X_CSRFTOKEN=csrf)
                self.assertEqual(r.status_code, 200)
            self.browser.cookies[cookie_auth.refresh_cookie_name()] = "not-a-token"
            codes = [self.browser.post(self.URL, {}, format="json", HTTP_X_CSRFTOKEN=csrf).status_code
                     for _ in range(4)]
            self.assertIn(429, codes)

    @override_settings(AUTH_TRANSPORT="header")
    def test_header_mode_has_nothing_to_renew(self):
        r = APIClient().post(self.URL, {}, format="json")
        self.assertEqual((r.status_code, r.data), (200, {"renewed": False}))


class SignOutWithOnlyARefreshTokenTests(APITestBase):
    """WEB-02. The SPA falls back to this call, with no Authorization header, when its access token has expired."""

    def test_the_refresh_token_is_revoked_and_the_sign_out_is_audited(self):
        refresh = RefreshToken.for_user(self.manager)
        r = APIClient().post("/api/auth/token/clear/", {"refresh": str(refresh)}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        self.assertEqual(r.data["revoked"], 1)
        self.assertTrue(BlacklistedToken.objects.filter(
            token=OutstandingToken.objects.get(jti=refresh["jti"])).exists())
        row = AuditLog.objects.filter(action="logout", object_id=str(self.manager.pk)).first()
        self.assertIsNotNone(row, "a sign-out that revokes a token leaves a trail")
        self.assertEqual(row.user_id, self.manager.pk)
        self.assertEqual(row.workspace_id, self.manager.workspace_id)

    def test_a_token_that_revokes_nothing_leaves_no_row(self):
        before = AuditLog.objects.filter(action="logout").count()
        r = APIClient().post("/api/auth/token/clear/", {"refresh": "garbage"}, format="json")
        self.assertEqual((r.status_code, r.data["revoked"]), (200, 0))
        self.assertEqual(AuditLog.objects.filter(action="logout").count(), before)

    def test_an_expired_access_token_in_the_header_is_why_the_client_leaves_it_off(self):
        # With a dead Bearer the authentication class refuses the request before the view runs.
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework_simplejwt.tokens import AccessToken

        stale = AccessToken.for_user(self.manager)
        stale.set_exp(from_time=timezone.now() - timedelta(hours=2))
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {stale}")
        r = client.post("/api/auth/token/clear/", {"refresh": str(RefreshToken.for_user(self.manager))},
                        format="json")
        self.assertEqual(r.status_code, 401)
