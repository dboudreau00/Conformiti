"""Audit trail: what the middleware records, what it must never record, and
who can read it."""
from audit.models import AuditLog
from testutils import APITestBase


class AuditMiddlewareTests(APITestBase):
    def test_create_records_new_id_and_field_names(self):
        c = self.client_for(self.manager)
        r = c.post("/api/risks/", {"title": "Gap", "likelihood": 2, "impact": 3, "description": "secret text"}, format="json")
        self.assertEqual(r.status_code, 201)
        entry = AuditLog.objects.filter(object_type="risks", action="create").latest("timestamp")
        self.assertEqual(entry.user, self.manager)
        self.assertEqual(entry.object_id, str(r.data["id"]))
        self.assertIn("fields=", entry.detail)
        self.assertIn("title", entry.detail)
        self.assertNotIn("secret text", entry.detail)  # names only, never values

    def test_password_fields_never_appear(self):
        c = self.client_for(self.admin)
        c.patch(f"/api/users/{self.viewer.pk}/", {"password": "Another-Strong-Pass1", "job_title": "x"}, format="json")
        entry = AuditLog.objects.filter(object_type="users", action="update").latest("timestamp")
        self.assertIn("job_title", entry.detail)
        self.assertNotIn("password", entry.detail)
        self.assertNotIn("Another-Strong", entry.detail)

    def test_failed_and_read_requests_are_not_logged(self):
        before = AuditLog.objects.count()
        c = self.client_for(self.viewer)
        c.get("/api/controls/")
        c.post("/api/risks/", {"title": "nope"}, format="json")  # 403
        self.assertEqual(AuditLog.objects.count(), before)

    def test_notification_state_is_not_audited(self):
        before = AuditLog.objects.count()
        self.client_for(self.viewer).post("/api/notifications/mark-read/")
        self.assertEqual(AuditLog.objects.count(), before)

    def test_client_ip_prefers_last_forwarded_hop_and_validates(self):
        c = self.client_for(self.manager)
        c.post("/api/risks/", {"title": "A"}, format="json", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.9")
        self.assertEqual(AuditLog.objects.latest("timestamp").ip_address, "10.0.0.9")
        c.post("/api/risks/", {"title": "B"}, format="json", HTTP_X_FORWARDED_FOR="not-an-ip")
        entry = AuditLog.objects.latest("timestamp")
        self.assertIsNone(entry.ip_address)
        self.assertEqual(entry.object_type, "risks")  # the row was still written


class AuditApiTests(APITestBase):
    def test_read_only_and_gated(self):
        AuditLog.objects.create(user=self.manager, action="update", object_type="documents", object_id="1", detail="x")
        for u in (self.admin, self.auditor, self.manager):
            self.assertEqual(self.client_for(u).get("/api/audit-log/").status_code, 200, u.username)
        for u in (self.owner, self.viewer):
            self.assertEqual(self.client_for(u).get("/api/audit-log/").status_code, 403, u.username)
        a = self.client_for(self.admin)
        self.assertEqual(a.post("/api/audit-log/", {"action": "x"}, format="json").status_code, 405)
        entry = AuditLog.objects.first()
        self.assertEqual(a.delete(f"/api/audit-log/{entry.pk}/").status_code, 405)
        self.assertEqual(a.patch(f"/api/audit-log/{entry.pk}/", {"detail": "y"}, format="json").status_code, 405)
        facets = a.get("/api/audit-log/facets/").data
        self.assertIn("update", facets["actions"])
        self.assertEqual(a.get("/api/audit-log/?days=notanumber").status_code, 200)

    def test_facets_are_deduplicated(self):
        """The model's Meta ordering must not leak into the DISTINCT: many
        entries sharing an action have to collapse to one option."""
        for i in range(4):
            AuditLog.objects.create(user=self.manager, action="create", object_type="risks", object_id=str(i))
            AuditLog.objects.create(user=self.admin, action="update", object_type="documents", object_id=str(i))
        facets = self.client_for(self.admin).get("/api/audit-log/facets/").data
        self.assertEqual(sorted(facets["actions"]), ["create", "update"])
        self.assertEqual(sorted(facets["object_types"]), ["documents", "risks"])
        self.assertEqual(len(facets["users"]), len({u["username"] for u in facets["users"]}))
