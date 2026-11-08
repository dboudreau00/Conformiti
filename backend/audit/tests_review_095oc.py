"""0.9.5oc review round, audit trail."""
import json

from audit.middleware import MAX_DETAIL
from audit.models import AuditLog
from testutils import APITestBase


class PaddedBodyFieldNamesTests(APITestBase):
    """TEN-04: a body too big to parse ahead of the view, or with many keys, still names the fields it changed."""

    def patch_user(self, body):
        r = self.client_for(self.admin).patch(f"/api/users/{self.viewer.pk}/", body, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return AuditLog.objects.filter(object_type="users", action="update").latest("timestamp").detail

    def test_a_body_over_the_inspection_cap_still_names_role_and_is_active(self):
        detail = self.patch_user({"pad": "x" * 70000, "role": self.roles["Auditor"].pk, "is_active": False})
        self.assertIn("role", detail)
        self.assertIn("active status", detail)
        self.assertNotIn("xxxx", detail)

    def test_names_that_do_not_fit_are_counted_and_privileged_ones_come_first(self):
        body = {f"padding_field_number_{i:02d}": 1 for i in range(30)}
        body.update({"job_title": "Analyst", "role": self.roles["Auditor"].pk, "is_active": False})
        detail = self.patch_user(body)
        self.assertLessEqual(len(detail), MAX_DETAIL)
        listed = detail.split(", set ", 1)[1]
        self.assertTrue(listed.startswith("role, active status, "), listed)
        shown, left = listed.rsplit(" and ", 1)
        self.assertRegex(left, r"^\d+ more$")
        self.assertEqual(len(shown.split(", ")) + int(left.split()[0]), 33)

    def test_a_charset_parameter_does_not_hide_the_names_of_a_big_body(self):
        body = json.dumps({"pad": "x" * 70000, "role": self.roles["Auditor"].pk, "is_active": False})
        r = self.client_for(self.admin).patch(f"/api/users/{self.viewer.pk}/", body,
                                              content_type="application/json; charset=utf-8")
        self.assertEqual(r.status_code, 200, r.data)
        detail = AuditLog.objects.filter(object_type="users", action="update").latest("timestamp").detail
        self.assertIn("role", detail)
        self.assertIn("active status", detail)

    def test_a_long_key_cannot_use_up_the_width(self):
        detail = self.patch_user({"k" * 5000: 1, "role": self.roles["Auditor"].pk})
        self.assertIn(", set role and k", detail)
        self.assertLessEqual(len(detail), MAX_DETAIL)

    def test_password_fields_are_still_never_named_in_a_big_body(self):
        detail = self.patch_user({"pad": "x" * 70000, "password": "Another-Strong-Pass1", "job_title": "x"})
        self.assertIn("job title", detail)
        self.assertNotIn("password", detail)
        self.assertNotIn("Another-Strong", detail)

    def test_a_small_body_lists_every_name_without_a_counter(self):
        detail = self.patch_user({"job_title": "Analyst", "is_active": True})
        self.assertTrue(detail.endswith(", set active status and job title"), detail)

    def test_the_detail_helper_counts_what_it_leaves_out(self):
        from audit.middleware import _detail

        text = _detail("changed vendor 3", ",".join(f"name{i:03d}" * 3 for i in range(40)))
        self.assertLessEqual(len(text), MAX_DETAIL)
        self.assertRegex(text, r" and \d+ more$")
        self.assertEqual(_detail("changed vendor 3", ""), "changed vendor 3")
