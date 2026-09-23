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

    def test_feed_does_not_name_a_linked_document_the_caller_cannot_open(self):
        hidden = make_doc(self.tree.ctrl1, self.owner, name="Hidden")
        shown = make_doc(self.tree.ctrl2, self.owner, name="Shown")
        grant(self.tree.ctrl2, user=self.viewer, level=VIEW)
        m = self.client_for(self.manager)
        for title, doc in (("Hidden audit", hidden), ("Shown audit", shown)):
            r = m.post("/api/calendar/", {"title": title, "date": "2099-02-01", "document": doc.pk}, format="json")
            self.assertEqual(r.status_code, 201)
        window = "/api/calendar/feed/?start=2099-01-01&end=2099-12-31"
        as_viewer = {i["title"]: i["document"] for i in self.client_for(self.viewer).get(window).data}
        self.assertEqual(as_viewer, {"Hidden audit": None, "Shown audit": shown.pk})
        as_manager = {i["title"]: i["document"] for i in m.get(window).data}
        self.assertEqual(as_manager, {"Hidden audit": hidden.pk, "Shown audit": shown.pk})

    def test_list_and_detail_withhold_the_document_the_feed_withholds(self):
        hidden = make_doc(self.tree.ctrl1, self.owner, name="Hidden")
        shown = make_doc(self.tree.ctrl2, self.owner, name="Shown")
        grant(self.tree.ctrl2, user=self.viewer, level=VIEW)
        m = self.client_for(self.manager)
        ids = {}
        for title, doc in (("Hidden audit", hidden), ("Shown audit", shown)):
            r = m.post("/api/calendar/", {"title": title, "date": "2099-02-01", "document": doc.pk}, format="json")
            self.assertEqual(r.status_code, 201)
            ids[title] = r.data["id"]
        v = self.client_for(self.viewer)
        listed = v.get("/api/calendar/").data
        rows = listed.get("results", listed) if isinstance(listed, dict) else listed
        self.assertEqual({i["title"]: i["document"] for i in rows},
                         {"Hidden audit": None, "Shown audit": shown.pk})
        self.assertIsNone(v.get(f"/api/calendar/{ids['Hidden audit']}/").data["document"])
        self.assertEqual(v.get(f"/api/calendar/{ids['Shown audit']}/").data["document"], shown.pk)
        # The event itself still holds the link: only the reader's view changes.
        self.assertEqual(m.get(f"/api/calendar/{ids['Hidden audit']}/").data["document"], hidden.pk)

    def test_a_nameless_assignee_is_named_by_username(self):
        """createsuperuser asks for no first or last name; such an assignee
        showed as nobody, on the event and in the merged feed."""
        from testutils import make_user

        root = make_user("rootadmin", self.roles["Administrator"], first_name="", last_name="")
        m = self.client_for(self.manager)
        r = m.post("/api/calendar/", {"title": "Fieldwork", "date": "2099-03-01", "assignee": root.pk},
                   format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["assignee_name"], "rootadmin")
        m.post("/api/calendar/", {"title": "Unassigned", "date": "2099-03-02"}, format="json")
        make_doc(self.tree.ctrl1, root, name="Root policy", days=10)
        feed = {i["title"]: i["assignee"] for i in m.get("/api/calendar/feed/").data}
        self.assertEqual(feed["Fieldwork"], "rootadmin")
        self.assertEqual(feed["Review due: Root policy"], "rootadmin")
        self.assertIsNone(feed["Unassigned"])
