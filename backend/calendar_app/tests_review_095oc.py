from datetime import timedelta

from django.utils import timezone

from calendar_app.models import CalendarEvent
from testutils import APITestBase


class FeedWindowTests(APITestBase):
    """PRG-09 (and the calendar part of ROB-07): the feed returns what overlaps its window and is bounded."""

    def setUp(self):
        super().setUp()
        self.m = self.client_for(self.manager)
        self.viewer_client = self.client_for(self.viewer)

    def titles(self, query):
        r = self.viewer_client.get(f"/api/calendar/feed/{query}")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        return [i["title"] for i in r.data]

    def test_a_multi_day_event_shows_in_a_window_after_its_start(self):
        r = self.m.post("/api/calendar/", {"title": "ISO audit", "event_type": "audit", "date": "2026-01-20",
                                           "end_date": "2026-03-15"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.titles("?start=2026-01-26&end=2026-03-01"), ["ISO audit"])
        self.assertEqual(self.titles("?start=2026-03-15&end=2026-04-26"), ["ISO audit"])
        self.assertEqual(self.titles("?start=2026-03-16&end=2026-04-26"), [])
        self.assertEqual(self.titles("?start=2025-12-01&end=2026-01-19"), [])

    def test_a_single_day_event_still_needs_its_date_in_the_window(self):
        self.m.post("/api/calendar/", {"title": "Board", "date": "2026-02-10"}, format="json")
        self.assertEqual(self.titles("?start=2026-02-10&end=2026-02-10"), ["Board"])
        self.assertEqual(self.titles("?start=2026-02-11&end=2026-02-20"), [])
        self.assertEqual(self.titles("?start=2026-02-01&end=2026-02-09"), [])

    def test_no_window_is_a_bounded_default(self):
        today = timezone.localdate()
        for title, offset in (("Near", 10), ("Far", 2000), ("Long ago", -2000)):
            CalendarEvent.objects.create(title=title, date=today + timedelta(days=offset), created_by=self.manager)
        self.assertEqual(self.titles(""), ["Near"])

    def test_bad_dates_and_spans_are_refused(self):
        for query in ("?start=banana&end=2026-01-01", "?start=2026-01-01&end=2026-13-45",
                      "?start=2026-02-01&end=2026-01-01", "?start=2020-01-01&end=2026-01-01"):
            with self.subTest(query=query):
                self.assertEqual(self.viewer_client.get(f"/api/calendar/feed/{query}").status_code, 400)

    def test_a_window_past_the_ends_of_the_calendar_is_refused_not_a_500(self):
        for query in ("?start=9999-06-01", "?end=0001-03-01"):
            with self.subTest(query):
                self.assertEqual(self.viewer_client.get(f"/api/calendar/feed/{query}").status_code, 400)

    def test_a_reversed_span_is_not_stored(self):
        bad = {"title": "Backwards", "date": "2026-03-10", "end_date": "2026-03-01"}
        r = self.m.post("/api/calendar/", bad, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("end_date", r.data)
        ok = self.m.post("/api/calendar/", {"title": "Fine", "date": "2026-03-10", "end_date": "2026-03-12"},
                         format="json")
        self.assertEqual(ok.status_code, 201)
        url = f"/api/calendar/{ok.data['id']}/"
        self.assertEqual(self.m.patch(url, {"end_date": "2026-03-01"}, format="json").status_code, 400)
        self.assertEqual(self.m.patch(url, {"end_date": None}, format="json").status_code, 200)

    def test_an_auditor_cannot_write_an_event(self):
        r = self.client_for(self.auditor).post("/api/calendar/", {"title": "x", "date": "2026-03-10"}, format="json")
        self.assertEqual(r.status_code, 403)
