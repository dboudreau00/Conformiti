import io

from django.core.management import call_command

from compliance.models import Control, Framework
from testutils import APITestBase


class FrameworkWriteTests(APITestBase):
    def test_a_framework_cannot_be_deleted_over_the_api(self):
        key = self.tree.framework.key
        for user in (self.admin, self.manager):
            with self.subTest(user=user.username):
                response = self.client_for(user).delete(f"/api/frameworks/{key}/")
                self.assertEqual(response.status_code, 405)
        self.assertTrue(Framework.objects.filter(key=key).exists())
        self.assertTrue(Control.objects.filter(category__framework__key=key).exists())

    def test_put_is_not_offered(self):
        key = self.tree.framework.key
        response = self.client_for(self.admin).put(
            f"/api/frameworks/{key}/", {"key": key, "name": "Replaced"}, format="json")
        self.assertEqual(response.status_code, 405)

    def test_the_key_cannot_be_renamed(self):
        admin = self.client_for(self.admin)
        key = self.tree.framework.key
        refused = admin.patch(f"/api/frameworks/{key}/", {"key": "renamed"}, format="json")
        self.assertEqual(refused.status_code, 400, refused.data)
        self.assertIn("key", refused.data)
        self.assertTrue(Framework.objects.filter(key=key).exists())
        self.assertFalse(Framework.objects.filter(key="renamed").exists())

    def test_the_other_fields_stay_editable_and_the_same_key_may_be_resent(self):
        admin = self.client_for(self.admin)
        key = self.tree.framework.key
        edited = admin.patch(f"/api/frameworks/{key}/", {"name": "Test Framework, edited"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        resent = admin.patch(f"/api/frameworks/{key}/", {"key": key, "description": "Resent"}, format="json")
        self.assertEqual(resent.status_code, 200, resent.data)
        self.assertEqual(Framework.objects.get(key=key).description, "Resent")

    def test_seeding_after_a_refused_rename_adds_no_second_copy(self):
        call_command("seed_frameworks", verbosity=0, stdout=io.StringIO())
        admin = self.client_for(self.admin)
        before = Framework.objects.filter(name__icontains="SOC 2").count()
        admin.patch("/api/frameworks/soc2/", {"key": "soc2-renamed"}, format="json")
        call_command("seed_frameworks", verbosity=0, stdout=io.StringIO())
        self.assertEqual(Framework.objects.filter(name__icontains="SOC 2").count(), before)

    def test_a_framework_can_still_be_created(self):
        response = self.client_for(self.admin).post(
            "/api/frameworks/", {"key": "custom1", "name": "Custom"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
