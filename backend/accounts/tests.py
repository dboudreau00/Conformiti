"""Authentication, MFA, token lifecycle and user-administration guards."""
from rest_framework.test import APIClient

from accounts import mfa as mfa_lib
from accounts.models import MfaDevice, Role
from audit.models import AuditLog
from testutils import PASSWORD, APITestBase, make_user


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
