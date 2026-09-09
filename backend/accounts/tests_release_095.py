"""0.9.5: an administrator setting a password ends the person's sessions, and
the boot-time seed reaches every workspace."""
from io import StringIO

from django.core.management import call_command
from rest_framework.test import APIClient

from accounts import tenancy
from accounts.models import Role, Workspace
from compliance.models import Framework
from testutils import PASSWORD, APITestBase


class AdminPasswordResetTests(APITestBase):
    def test_setting_somebody_elses_password_revokes_their_refresh_tokens(self):
        login = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD},
                                 format="json")
        self.assertEqual(login.status_code, 200)
        refresh = login.data["refresh"]
        # The token is live.
        self.assertEqual(APIClient().post("/api/auth/token/refresh/", {"refresh": refresh},
                                          format="json").status_code, 200)

        r = self.client_for(self.admin).patch(
            f"/api/users/{self.owner.pk}/", {"password": "Brand-New-Passw0rd!"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

        # And now it is not: the hijacked session the reset was meant to end
        # ends with it. The person's own change already did this; the
        # administrator's path did not.
        again = APIClient().post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(APIClient().post("/api/auth/token/",
                                          {"username": "owen", "password": "Brand-New-Passw0rd!"},
                                          format="json").status_code, 200)

    def test_an_edit_without_a_password_keeps_sessions(self):
        login = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD},
                                 format="json")
        refresh = login.data["refresh"]
        r = self.client_for(self.admin).patch(
            f"/api/users/{self.owner.pk}/", {"first_name": "Owen"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(APIClient().post("/api/auth/token/refresh/", {"refresh": refresh},
                                          format="json").status_code, 200)


class SeedEveryWorkspaceTests(APITestBase):
    def test_all_workspaces_seeds_each_organisation(self):
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-ltd")
        Workspace.objects.create(name="Archived", slug="archived", is_active=False)
        out = StringIO()
        call_command("seed_frameworks", "--all-workspaces", stdout=out)
        text = out.getvalue()
        self.assertIn("beta-ltd", text)
        self.assertIn("complete in 2 workspace(s)", text)
        with tenancy.scoped(beta):
            self.assertTrue(Framework.objects.filter(key="soc2").exists())
            self.assertTrue(Role.objects.filter(name="Auditor").exists())
        with tenancy.scoped(Workspace.objects.get(slug="archived")):
            self.assertFalse(Framework.objects.exists(), "archived workspaces are left alone")

    def test_the_single_workspace_form_is_unchanged(self):
        out = StringIO()
        call_command("seed_frameworks", "--workspace", "default", stdout=out)
        self.assertIn("Seeding complete.", out.getvalue())
