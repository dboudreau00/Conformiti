"""A clock that steps back (a VM after a sleep or time sync) must not sign out the person who just signed in: PyJWT
refuses a token whose ``iat`` is ahead of the checking clock, so a small leeway is configured."""
from datetime import timedelta

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts import cookie_auth
from testutils import APITestBase


def ahead(token, seconds):
    token.set_iat(at_time=timezone.now() + timedelta(seconds=seconds))
    return token


class ClockSkewTests(APITestBase):
    def bearer(self, user, seconds):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {ahead(AccessToken.for_user(user), seconds)}")
        return client

    def test_a_token_a_few_seconds_ahead_of_this_clock_is_accepted(self):
        self.assertEqual(self.bearer(self.viewer, 5).get("/api/users/me/").status_code, 200)

    def test_a_token_dated_well_into_the_future_is_still_refused(self):
        self.assertEqual(self.bearer(self.viewer, 600).get("/api/users/me/").status_code, 401)

    def test_the_cookie_session_probe_reads_the_same_leeway(self):
        with override_settings(AUTH_TRANSPORT="cookie"):
            client = APIClient()
            client.cookies[cookie_auth.access_cookie_name()] = str(ahead(AccessToken.for_user(self.viewer), 5))
            body = client.get("/api/auth/session/").json()
            self.assertTrue(body["authenticated"], body)
            far = APIClient()
            far.cookies[cookie_auth.access_cookie_name()] = str(ahead(AccessToken.for_user(self.viewer), 600))
            self.assertEqual(far.get("/api/auth/session/").status_code, 401)

    def test_a_refresh_token_a_few_seconds_ahead_renews(self):
        with override_settings(AUTH_TRANSPORT="header"):
            refresh = str(ahead(RefreshToken.for_user(self.viewer), 5))
            r = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
            self.assertEqual(r.status_code, 200, getattr(r, "data", r))

    def test_the_leeway_is_a_setting_and_stays_small(self):
        leeway = settings.SIMPLE_JWT["LEEWAY"]
        self.assertGreaterEqual(leeway, 5)
        self.assertLessEqual(leeway, 120)
