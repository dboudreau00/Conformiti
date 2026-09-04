"""Per-user notification feed and the review-reminder scan."""
from django.core import mail
from django.test import override_settings

from documents.models import Document
from notifications.tasks import OVERDUE, run_review_scan
from testutils import APITestBase, make_doc


class FeedTests(APITestBase):
    def test_feed_is_scoped_to_ownership_and_role(self):
        make_doc(self.tree.ctrl1, self.owner, name="Late", days=-3)
        make_doc(self.tree.ctrl1, self.owner, name="Soon", days=5)
        make_doc(self.tree.ctrl1, self.manager, name="Far", days=200)
        owner_feed = self.client_for(self.owner).get("/api/notifications/").data
        titles = [i["title"] for i in owner_feed["results"]]
        self.assertIn("Review overdue: Late", titles)
        self.assertIn("Review due soon: Soon", titles)
        self.assertEqual(owner_feed["unread"], 2)
        # the viewer owns nothing and has no digests
        self.assertEqual(self.client_for(self.viewer).get("/api/notifications/").data["results"], [])
        # the manager gets the org-wide digest, not owen's per-item notices
        mgr = [i["key"] for i in self.client_for(self.manager).get("/api/notifications/").data["results"]]
        self.assertIn("digest-docs-overdue", mgr)
        self.assertIn("digest-evidence-gap", mgr)
        self.assertNotIn("doc-overdue:1", mgr)

    def test_mark_read_and_dismiss(self):
        doc = make_doc(self.tree.ctrl1, self.owner, name="Late", days=-3)
        c = self.client_for(self.owner)
        self.assertEqual(c.post("/api/notifications/mark-read/").data["unread"], 0)
        self.assertEqual(c.get("/api/notifications/").data["unread"], 0)
        # dismissing a key that isn't in the feed is refused (no unbounded receipts)
        self.assertEqual(c.post("/api/notifications/dismiss/", {"key": "made-up"}, format="json").status_code, 404)
        self.assertEqual(c.post("/api/notifications/dismiss/", {}, format="json").status_code, 400)
        r = c.post("/api/notifications/dismiss/", {"key": f"doc-overdue:{doc.pk}"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/notifications/").data["results"], [])


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local", REVIEW_ALERT_LEAD_DAYS=[30, 14, 7, 1])
class ReviewScanTests(APITestBase):
    def test_scan_sends_once_per_window_and_marks_overdue(self):
        late = make_doc(self.tree.ctrl1, self.owner, name="Late", days=-1)
        soon = make_doc(self.tree.ctrl1, self.owner, name="Soon", days=6)
        make_doc(self.tree.ctrl1, self.owner, name="Far", days=120)
        self.assertEqual(run_review_scan(dry_run=True), 2)
        self.assertEqual(len(mail.outbox), 0)
        late.refresh_from_db()
        self.assertEqual(late.reminders_sent, [])   # dry run persisted nothing

        self.assertEqual(run_review_scan(), 2)
        self.assertEqual(len(mail.outbox), 2)
        recipients = {tuple(m.to) for m in mail.outbox}
        self.assertIn(("owen@test.local", "grc@test.local"), recipients)
        late.refresh_from_db()
        soon.refresh_from_db()
        self.assertEqual(late.status, Document.Status.EXPIRED)
        self.assertEqual(late.reminders_sent, [OVERDUE])
        self.assertEqual(soon.reminders_sent, [7, 14, 30])  # every window already passed is marked
        self.assertIn("[Overdue]", mail.outbox[0].subject + mail.outbox[1].subject)

        # second run: nothing new
        self.assertEqual(run_review_scan(), 0)
        self.assertEqual(len(mail.outbox), 2)

        # marking reviewed resets the dedupe state
        self.client_for(self.manager).post(f"/api/documents/{late.pk}/mark_reviewed/")
        late.refresh_from_db()
        self.assertEqual(late.reminders_sent, [])
        self.assertEqual(late.status, Document.Status.APPROVED)

    def test_one_failing_send_does_not_abort_the_run(self):
        from unittest import mock
        make_doc(self.tree.ctrl1, self.owner, name="A", days=-1)
        make_doc(self.tree.ctrl1, self.owner, name="B", days=-1)
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("smtp down")
            return True

        with mock.patch("notifications.tasks.send_templated_email", side_effect=flaky):
            self.assertEqual(run_review_scan(), 1)
        # the failed document was left untouched so it retries next time
        self.assertEqual(Document.objects.filter(reminders_sent=[]).count(), 1)
