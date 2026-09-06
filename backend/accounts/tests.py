"""Authentication, MFA, token lifecycle and user-administration guards."""
from rest_framework.test import APIClient

from accounts import mfa as mfa_lib
from accounts.models import MfaDevice, Role
from audit.models import AuditLog
from testutils import PASSWORD, APITestBase, make_user
from django.test import override_settings


class LoginTests(APITestBase):
    def test_login_returns_token_pair_and_is_audited(self):
        r = APIClient().post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        entry = AuditLog.objects.filter(action="login", user=self.manager).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.object_type, "auth")

    def test_bad_password_is_rejected_and_audited_without_a_user(self):
        r = APIClient().post("/api/auth/token/", {"username": "mia", "password": "nope"}, format="json")
        self.assertEqual(r.status_code, 401)
        entry = AuditLog.objects.filter(action="login_failed").first()
        self.assertIsNotNone(entry)
        self.assertIsNone(entry.user)
        self.assertIn("mia", entry.detail)
        self.assertNotIn("nope", entry.detail)  # the password never reaches the trail

    def test_inactive_user_cannot_log_in(self):
        self.viewer.is_active = False
        self.viewer.save()
        r = APIClient().post("/api/auth/token/", {"username": "val", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_login_is_rate_limited_per_client(self):
        # DRF binds THROTTLE_RATES at import time, so exercise the shipped
        # default (8/min) rather than overriding it: the 9th attempt is refused
        # even with the correct password.
        c = APIClient()
        for _ in range(8):
            self.assertEqual(c.post("/api/auth/token/", {"username": "mia", "password": "wrong"}, format="json").status_code, 401)
        r = c.post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 429)
        # a different client is unaffected
        self.assertEqual(APIClient().post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json", REMOTE_ADDR="10.9.9.9").status_code, 200)

    def test_health_endpoint_is_open_and_unthrottled(self):
        c = APIClient()
        for _ in range(35):  # > the 30/min anonymous ceiling
            r = c.get("/api/health/")
            self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "ok")
        self.assertEqual(r.data["database"], "ok")
        self.assertIn("version", r.data)
        self.assertFalse(r.data["demo_accounts"])


class TokenLifecycleTests(APITestBase):
    def _login(self):
        r = APIClient().post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json")
        return r.data["access"], r.data["refresh"]

    def test_refresh_rotates_and_blacklists_the_old_token(self):
        _, refresh = self._login()
        r1 = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertIn("refresh", r1.data)
        self.assertNotEqual(r1.data["refresh"], refresh)
        # the consumed refresh token is dead
        r2 = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r2.status_code, 401)
        # the new one works
        r3 = APIClient().post("/api/auth/token/refresh/", {"refresh": r1.data["refresh"]}, format="json")
        self.assertEqual(r3.status_code, 200)

    def test_logout_revokes_the_refresh_token(self):
        access, refresh = self._login()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        r = c.post("/api/auth/logout/", {"refresh": refresh}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["refresh_revoked"])
        r2 = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(r2.status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action="logout", user=self.manager).exists())

    def test_logout_requires_authentication(self):
        r = APIClient().post("/api/auth/logout/", {"refresh": "x"}, format="json")
        self.assertEqual(r.status_code, 401)


class MfaTests(APITestBase):
    def _enable(self, user):
        c = self.client_for(user)
        setup = c.post("/api/auth/mfa/setup/")
        self.assertEqual(setup.status_code, 200)
        secret = setup.data["secret"]
        self.assertIn("otpauth://totp/", setup.data["otpauth_uri"])
        # device exists but is not enabled yet -> login still password-only
        self.assertFalse(user.mfa_device.enabled)
        verify = c.post("/api/auth/mfa/verify/", {"code": mfa_lib.totp(secret)}, format="json")
        self.assertEqual(verify.status_code, 200)
        self.assertEqual(len(verify.data["backup_codes"]), 10)
        return secret, verify.data["backup_codes"]

    def test_full_enrollment_and_login_flow(self):
        secret, codes = self._enable(self.manager)
        anon = APIClient()
        # password alone is now a challenge, not a token
        r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data.get("mfa_required"))
        self.assertNotIn("access", r.data)
        # wrong code
        r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD, "otp": "000000"}, format="json")
        self.assertEqual(r.status_code, 401)
        # right code
        r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD, "otp": mfa_lib.totp(secret)}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        # backup code works exactly once
        r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD, "otp": codes[0]}, format="json")
        self.assertEqual(r.status_code, 200)
        r = anon.post("/api/auth/token/", {"username": "mia", "password": PASSWORD, "otp": codes[0]}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action="login_failed", detail__contains="second factor").exists())

    def test_wrong_code_does_not_enable(self):
        c = self.client_for(self.owner)
        c.post("/api/auth/mfa/setup/")
        r = c.post("/api/auth/mfa/verify/", {"code": "123456"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(MfaDevice.objects.get(user=self.owner).enabled)

    def test_disable_and_regenerate_require_password(self):
        self._enable(self.owner)
        c = self.client_for(self.owner)
        self.assertEqual(c.post("/api/auth/mfa/disable/", {"password": "wrong"}, format="json").status_code, 400)
        self.assertEqual(c.post("/api/auth/mfa/backup-codes/", {"password": "wrong"}, format="json").status_code, 400)
        r = c.post("/api/auth/mfa/backup-codes/", {"password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.post("/api/auth/mfa/disable/", {"password": PASSWORD}, format="json").status_code, 200)
        self.assertFalse(MfaDevice.objects.filter(user=self.owner).exists())

    def test_admin_reset_mfa(self):
        self._enable(self.owner)
        self.assertEqual(self.client_for(self.viewer).post(f"/api/users/{self.owner.pk}/reset_mfa/").status_code, 403)
        r = self.client_for(self.admin).post(f"/api/users/{self.owner.pk}/reset_mfa/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(MfaDevice.objects.filter(user=self.owner).exists())

    def test_rfc_vectors(self):
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(mfa_lib.hotp(secret, 0), "755224")
        self.assertEqual(mfa_lib.totp(secret, at=59, digits=8), "94287082")
        self.assertTrue(mfa_lib.verify(secret, mfa_lib.totp(secret, at=1000), at=1000 + 29))
        self.assertFalse(mfa_lib.verify(secret, mfa_lib.totp(secret, at=1000), at=1000 + 120))


class UserAdminGuardTests(APITestBase):
    def test_viewer_can_read_but_not_write_users(self):
        c = self.client_for(self.viewer)
        self.assertEqual(c.get("/api/users/").status_code, 200)
        r = c.post("/api/users/", {"username": "new", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(c.patch(f"/api/users/{self.owner.pk}/", {"is_active": False}, format="json").status_code, 403)

    def test_admin_set_password_is_validated(self):
        c = self.client_for(self.admin)
        r = c.patch(f"/api/users/{self.viewer.pk}/", {"password": "short"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("password", r.data)
        r = c.patch(f"/api/users/{self.viewer.pk}/", {"password": "Long-Enough-Passw0rd"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_create_user_cannot_set_superuser_or_staff(self):
        c = self.client_for(self.admin)
        r = c.post("/api/users/", {
            "username": "sneaky", "password": "Long-Enough-Passw0rd", "role": self.roles["Viewer"].pk,
            "is_superuser": True, "is_staff": True,
        }, format="json")
        self.assertEqual(r.status_code, 201)
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.get(username="sneaky")
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.is_staff)

    def test_cannot_deactivate_or_delete_self(self):
        c = self.client_for(self.admin)
        self.assertEqual(c.patch(f"/api/users/{self.admin.pk}/", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(c.delete(f"/api/users/{self.admin.pk}/").status_code, 403)

    def test_last_administrator_is_protected(self):
        # a non-superuser admin, and make ada (superuser) inactive so 'boss' is the last admin
        boss = make_user("boss", self.roles["Administrator"])
        self.admin.is_active = False
        self.admin.save()
        c = self.client_for(boss)
        other = make_user("other", self.roles["Administrator"])
        # demoting the *other* admin is fine while boss remains
        self.assertEqual(c.patch(f"/api/users/{other.pk}/", {"role": self.roles["Viewer"].pk}, format="json").status_code, 200)
        # boss can't demote themself at all
        self.assertEqual(c.patch(f"/api/users/{boss.pk}/", {"role": self.roles["Viewer"].pk}, format="json").status_code, 403)
        # and another admin can't strip boss now that boss is the last one
        self.admin.is_active = True
        self.admin.save()
        c2 = self.client_for(self.admin)
        self.admin.is_superuser = False  # pretend non-superuser admin
        self.admin.save()
        # ada is now also an admin via role, so boss is not the last -> allowed
        self.assertEqual(c2.patch(f"/api/users/{boss.pk}/", {"is_active": False}, format="json").status_code, 200)

    def test_non_superuser_cannot_touch_superuser(self):
        other_admin = make_user("boss", self.roles["Administrator"])
        c = self.client_for(other_admin)
        self.assertEqual(c.patch(f"/api/users/{self.admin.pk}/", {"job_title": "x"}, format="json").status_code, 403)
        self.assertEqual(c.delete(f"/api/users/{self.admin.pk}/").status_code, 403)

    def test_profile_patch_cannot_escalate(self):
        c = self.client_for(self.viewer)
        r = c.patch("/api/users/me/", {
            "job_title": "Analyst", "role": self.roles["Administrator"].pk, "is_active": False, "is_superuser": True,
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.job_title, "Analyst")
        self.assertEqual(self.viewer.role, self.roles["Viewer"])
        self.assertTrue(self.viewer.is_active)
        self.assertFalse(self.viewer.is_superuser)

    def test_change_password_verifies_current(self):
        c = self.client_for(self.viewer)
        r = c.post("/api/users/change_password/", {"current_password": "bad", "new_password": "Another-Strong-Pass1"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/users/change_password/", {"current_password": PASSWORD, "new_password": "Another-Strong-Pass1"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password("Another-Strong-Pass1"))

    def test_builtin_role_flags_are_locked_but_custom_roles_work(self):
        c = self.client_for(self.admin)
        viewer_role = self.roles["Viewer"]
        r = c.patch(f"/api/roles/{viewer_role.pk}/", {"can_manage_users": True}, format="json")
        self.assertEqual(r.status_code, 403)
        r = c.patch(f"/api/roles/{viewer_role.pk}/", {"description": "Read only"}, format="json")
        self.assertEqual(r.status_code, 200)
        r = c.post("/api/roles/", {"name": "Risk Lead", "can_manage_frameworks": True}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(Role.objects.get(name="Risk Lead").is_system)
        self.assertEqual(c.delete(f"/api/roles/{viewer_role.pk}/").status_code, 403)
        self.assertEqual(c.delete(f"/api/roles/{r.data['id']}/").status_code, 204)


class MfaSecretAtRestTests(APITestBase):
    """The TOTP secret is encrypted in the database but transparent to the app.

    The first test here is the one that matters: without a data descriptor on
    the field, Model.__init__ writes the raw column straight into the
    instance's __dict__ and wins the attribute lookup, so nothing ever
    decrypts -- and mfa.verify() would be handed a ciphertext.
    """

    def setUp(self):
        super().setUp()
        self.device = MfaDevice.objects.create(user=self.owner, secret="JBSWY3DPEHPK3PXP")

    def _raw(self):
        return MfaDevice.objects.filter(pk=self.device.pk).values_list("secret", flat=True).first()

    def test_plain_queryset_load_returns_plaintext(self):
        self.assertEqual(MfaDevice.objects.get(pk=self.device.pk).secret, "JBSWY3DPEHPK3PXP")

    def test_deferred_and_refreshed_loads_return_plaintext(self):
        self.assertEqual(MfaDevice.objects.only("secret").get(pk=self.device.pk).secret,
                         "JBSWY3DPEHPK3PXP")
        self.assertEqual(MfaDevice.objects.defer("secret").get(pk=self.device.pk).secret,
                         "JBSWY3DPEHPK3PXP")
        fresh = MfaDevice.objects.get(pk=self.device.pk)
        fresh.refresh_from_db()
        self.assertEqual(fresh.secret, "JBSWY3DPEHPK3PXP")

    def test_the_stored_column_is_ciphertext(self):
        raw = self._raw()
        self.assertTrue(raw.startswith("fc1$"))
        self.assertNotIn("JBSWY3DPEHPK3PXP", raw)

    def test_a_full_save_does_not_re_encrypt(self):
        device = MfaDevice.objects.get(pk=self.device.pk)
        device.save()
        self.assertEqual(self._raw().count("fc1$"), 1)
        self.assertEqual(MfaDevice.objects.get(pk=self.device.pk).secret, "JBSWY3DPEHPK3PXP")

    def test_ciphertext_moved_to_another_user_does_not_decrypt(self):
        """The AAD binds the envelope to user_id, so a ciphertext lifted from a
        database dump and written into someone else's row is inert."""
        stolen = self._raw()
        other = MfaDevice.objects.create(user=self.viewer, secret="AAAAAAAAAAAAAAAA")
        MfaDevice.objects.filter(pk=other.pk).update(secret=stolen)
        self.assertEqual(MfaDevice.objects.get(pk=other.pk).secret, "")

    def test_an_unreadable_secret_survives_a_full_save(self):
        """A mistyped key must degrade to read-only, never destroy the column:
        restoring the right key has to recover the secret."""
        before = self._raw()
        with override_settings(FIELD_ENCRYPTION_KEYS=["a-totally-different-key-000000000000"]):
            device = MfaDevice.objects.get(pk=self.device.pk)
            self.assertEqual(device.secret, "")
            device.save()
            self.assertEqual(self._raw(), before)
        self.assertEqual(MfaDevice.objects.get(pk=self.device.pk).secret, "JBSWY3DPEHPK3PXP")

    def test_login_still_demands_a_second_factor_when_the_secret_is_unreadable(self):
        """An unreadable secret must not become an authentication bypass."""
        self.device.enabled = True
        self.device.save()
        with override_settings(FIELD_ENCRYPTION_KEYS=["a-totally-different-key-000000000000"]):
            r = APIClient().post("/api/auth/token/",
                                 {"username": self.owner.username, "password": PASSWORD},
                                 format="json")
            # The second factor is still demanded (400 + mfa_required, the same
            # contract as a readable secret) and no tokens are issued.
            self.assertEqual(r.status_code, 400)
            self.assertTrue(r.data.get("mfa_required"))
            self.assertNotIn("access", r.data)
            # ...and a wrong code is still refused rather than waved through.
            r = APIClient().post("/api/auth/token/",
                                 {"username": self.owner.username, "password": PASSWORD,
                                  "otp": "000000"},
                                 format="json")
            self.assertNotIn("access", r.data)

    def test_backup_codes_still_work_when_the_secret_is_unreadable(self):
        """This is the documented recovery path, and the reason backup codes
        are deliberately left unencrypted."""
        self.device.enabled = True
        self.device.save()
        self.owner.set_backup_codes(["abcd-1234"])
        with override_settings(FIELD_ENCRYPTION_KEYS=["a-totally-different-key-000000000000"]):
            r = APIClient().post("/api/auth/token/",
                                 {"username": self.owner.username, "password": PASSWORD,
                                  "otp": "abcd-1234"}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertFalse(self.owner.verify_backup_code("abcd-1234"))   # single use

    def test_enrolment_and_verification_work_end_to_end(self):
        """The whole point: encryption must be invisible to the feature."""
        c = self.client_for(self.manager)
        setup = c.post("/api/auth/mfa/setup/", {}, format="json")
        self.assertEqual(setup.status_code, 200)
        secret = setup.data["secret"]
        stored = MfaDevice.objects.filter(user=self.manager).values_list("secret", flat=True).first()
        self.assertTrue(stored.startswith("fc1$"))
        self.assertNotIn(secret, stored)
        r = c.post("/api/auth/mfa/verify/", {"code": mfa_lib.totp(secret)}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(MfaDevice.objects.get(user=self.manager).enabled)


COOKIE = override_settings(AUTH_TRANSPORT="cookie", AUTH_COOKIE_SECURE=False)


@COOKIE
class CookieAuthTests(APITestBase):
    """The same tokens, delivered where script cannot read them."""

    def login(self, client=None, **extra):
        client = client or APIClient(enforce_csrf_checks=True)
        return client, client.post(
            "/api/auth/token/",
            {"username": "mia", "password": PASSWORD}, format="json", **extra)

    def test_login_sets_httponly_cookies_and_returns_no_tokens(self):
        client, r = self.login()
        self.assertEqual(r.status_code, 200, r.data)
        # The whole point: nothing usable in the body.
        self.assertNotIn("access", r.data)
        self.assertNotIn("refresh", r.data)
        self.assertTrue(r.data["authenticated"])

        access = r.cookies["conformiti_access"]
        refresh = r.cookies["conformiti_refresh"]
        for cookie in (access, refresh):
            self.assertTrue(cookie["httponly"])
            self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(access["path"], "/api/")
        # NOT /api/auth/ -- that prefix covers the MFA routes that return the
        # TOTP secret and the backup codes.
        self.assertEqual(refresh["path"], "/api/auth/token/")

    def test_the_cookie_alone_authenticates_a_read(self):
        client, _ = self.login()
        r = client.get("/api/users/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["username"], "mia")

    def test_an_unsafe_method_needs_the_csrf_header(self):
        client, login = self.login()
        token = login.cookies["csrftoken"].value
        r = client.patch("/api/users/me/", {"job_title": "No token"}, format="json")
        self.assertEqual(r.status_code, 403, "a cookie-authenticated write needs CSRF")
        r = client.patch("/api/users/me/", {"job_title": "With token"},
                         format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200, r.data)

    def test_a_bearer_header_still_works_and_needs_no_csrf(self):
        """API clients are unaffected by the transport setting: a header is not
        attached by the browser, so it cannot be forged cross-site."""
        pair = APIClient().post("/api/auth/token/",
                                {"username": "mia", "password": PASSWORD}, format="json")
        # In cookie mode the body is empty, so read the token from the cookie
        # the way a script never could -- this is a test, not the browser.
        access = pair.cookies["conformiti_access"].value
        client = APIClient(enforce_csrf_checks=True)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(client.get("/api/users/me/").status_code, 200)
        self.assertEqual(
            client.patch("/api/users/me/", {"job_title": "Via header"}, format="json").status_code,
            200)

    def test_the_csrf_token_rotates_across_the_login_boundary(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/auth/session/")           # seeds a pre-login token
        before = client.cookies.get("csrftoken")
        _, login = self.login(client)
        self.assertEqual(login.status_code, 200)
        after = login.cookies.get("csrftoken")
        self.assertIsNotNone(after)
        if before is not None:
            self.assertNotEqual(before.value, after.value,
                                "a pre-login token must not survive into the session")

    def test_refresh_reads_the_cookie_rotates_and_reissues(self):
        client, login = self.login()
        first = login.cookies["conformiti_refresh"].value
        r = client.post("/api/auth/token/refresh/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data, {"renewed": True}, "no tokens in the body")
        self.assertNotEqual(r.cookies["conformiti_refresh"].value, first,
                            "refresh tokens rotate")
        # The old one is blacklisted, as in header mode.
        self.assertEqual(
            APIClient().post("/api/auth/token/refresh/",
                             {"refresh": first}, format="json").status_code, 401)

    def test_refresh_without_a_cookie_is_refused(self):
        self.assertEqual(
            APIClient().post("/api/auth/token/refresh/", {}, format="json").status_code, 400)

    def test_the_session_probe_is_tolerant_and_reports_renewability(self):
        client = APIClient(enforce_csrf_checks=True)
        r = client.get("/api/auth/session/")
        self.assertEqual(r.status_code, 200, "a cold probe must not 401")
        self.assertFalse(r.data["authenticated"])
        self.assertEqual(r.data["transport"], "cookie")

        client, _ = self.login(client)
        r = client.get("/api/auth/session/")
        self.assertTrue(r.data["authenticated"])
        self.assertEqual(r.data["username"], "mia")

        # An expired access cookie with a live refresh cookie is renewable.
        client.cookies.pop("conformiti_access")
        r = client.get("/api/auth/session/")
        self.assertFalse(r.data["authenticated"])
        self.assertTrue(r.data["renewable"])

    def test_signing_out_works_even_after_the_access_cookie_has_expired(self):
        """The fail-open this closes: the SPA cannot clear an HttpOnly cookie,
        so a sign-out that 401d would leave a live 7-day credential in the
        browser while the interface said 'signed out'."""
        client, login = self.login()
        refresh = login.cookies["conformiti_refresh"].value
        token = client.cookies["csrftoken"].value
        client.cookies.pop("conformiti_access")

        r = client.post("/api/auth/session/clear/", {}, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.cookies["conformiti_access"].value, "")
        self.assertEqual(r.cookies["conformiti_refresh"].value, "")
        # ...and the refresh token really is dead.
        self.assertEqual(
            APIClient().post("/api/auth/token/refresh/",
                             {"refresh": refresh}, format="json").status_code, 401)

    def test_clearing_a_session_that_never_existed_still_succeeds(self):
        r = APIClient().post("/api/auth/session/clear/", {}, format="json")
        self.assertEqual(r.status_code, 200, "a client must always be able to finish signing out")

    def test_an_mfa_challenge_sets_no_cookies(self):
        device = MfaDevice.objects.create(user=self.manager, secret=mfa_lib.generate_secret())
        device.enabled = True
        device.save()
        r = APIClient().post("/api/auth/token/",
                             {"username": "mia", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("conformiti_access", r.cookies)
        self.assertNotIn("conformiti_refresh", r.cookies)

    def test_the_config_endpoint_tells_the_spa_which_transport_is_live(self):
        r = APIClient().get("/api/auth/config/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["transport"], "cookie")


class TransportDefaultTests(APITestBase):
    """Cookie transport is the default since 0.6.1 (the suite itself runs
    header mode from testutils so older tests keep reading tokens). Header
    mode stays available and behaves as it always did."""

    def test_the_shipped_default_is_cookie(self):
        from config import settings as raw
        self.assertEqual(raw.AUTH_TRANSPORT, "cookie")

    def test_header_mode_returns_tokens_and_sets_no_auth_cookies(self):
        r = APIClient().post("/api/auth/token/",
                             {"username": "mia", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        self.assertNotIn("conformiti_access", r.cookies)
        self.assertEqual(APIClient().get("/api/auth/config/").data["transport"], "header")

    def test_a_leftover_cookie_does_not_authenticate_in_header_mode(self):
        with override_settings(AUTH_TRANSPORT="cookie", AUTH_COOKIE_SECURE=False):
            login = APIClient().post("/api/auth/token/",
                                     {"username": "mia", "password": PASSWORD}, format="json")
            access = login.cookies["conformiti_access"].value
        client = APIClient()
        client.cookies["conformiti_access"] = access
        self.assertEqual(client.get("/api/users/me/").status_code, 401)

    def test_secure_cookies_carry_the_host_and_secure_prefixes(self):
        """Over https the access cookie is host-bound (Path=/, no Domain) and
        the refresh cookie keeps its narrow path under the __Secure- prefix."""
        with override_settings(AUTH_TRANSPORT="cookie", AUTH_COOKIE_SECURE=True):
            r = APIClient().post("/api/auth/token/",
                                 {"username": "mia", "password": PASSWORD}, format="json", secure=True)
            self.assertEqual(r.status_code, 200)
            self.assertNotIn("access", r.data)
            access = r.cookies["__Host-conformiti_access"]
            refresh = r.cookies["__Secure-conformiti_refresh"]
            self.assertEqual((access["path"], bool(access["secure"]), bool(access["httponly"])),
                             ("/", True, True))
            self.assertEqual((refresh["path"], bool(refresh["secure"])), ("/api/auth/token/", True))
            self.assertNotIn("conformiti_access", r.cookies)
            # Signing out expires the prefixed names and the pre-0.6.1 ones.
            client = APIClient()
            client.cookies["__Host-conformiti_access"] = access.value
            out = client.post("/api/auth/session/clear/", {}, format="json", secure=True)
            self.assertEqual(out.status_code, 200)
            for name in ("__Host-conformiti_access", "__Secure-conformiti_refresh",
                         "conformiti_access", "conformiti_refresh"):
                self.assertEqual(out.cookies[name]["max-age"], 0, name)
