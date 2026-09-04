"""Calendar write gates and the merged feed's visibility scoping."""
from documents.models import VIEW
from testutils import APITestBase, grant, make_doc


class CalendarTests(APITestBase):
    def test_write_requires_manage_documents(self):
        payload = {"title": "Audit fieldwork", "event_type": "audit", "date": "2026-10-01"}
        self.assertEqual(self.client_for(self.viewer).post("/api/calendar/", payload, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.auditor).post("/api/calendar/", payload, format="json").status_code, 403)
        r = self.client_for(self.owner).post("/api/calendar/", payload, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["created_by"], self.owner.pk)
        self.assertEqual(self.client_for(self.viewer).delete(f"/api/calendar/{r.data['id']}/").status_code, 403)

    def test_feed_merges_events_with_visible_review_dates_only(self):
        make_doc(self.tree.ctrl1, self.owner, name="Hidden", days=10)
        make_doc(self.tree.ctrl2, self.owner, name="Shown", days=10)
        grant(self.tree.ctrl2, user=self.viewer, level=VIEW)
        self.client_for(self.manager).post("/api/calendar/", {"title": "Board", "date": "2099-01-01"}, format="json")
        feed = self.client_for(self.viewer).get("/api/calendar/feed/").data
        titles = [i["title"] for i in feed]
        self.assertIn("Review due: Shown", titles)
        self.assertNotIn("Review due: Hidden", titles)
        self.assertIn("Board", titles)
        window = self.client_for(self.viewer).get("/api/calendar/feed/?start=2099-01-01&end=2099-12-31").data
        self.assertEqual([i["title"] for i in window], ["Board"])
