"""Per-user notification feed, the review-reminder scan and the email copy."""
import html
import re
from pathlib import Path
from types import SimpleNamespace

from django.core import mail
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

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


def _email_context(on):
    """Every variable the emails read, each optional part present (on) or
    absent (off), so both sides of every {% if %} get rendered."""
    ns = SimpleNamespace

    def opt(value):
        return value if on else ""

    return {
        "owner_name": "Owen", "assignee_name": "Ada", "sender": "Mia", "organisation": opt("Acme"),
        "user": ns(first_name=opt("Owen"), username="owen"), "cadence": "daily", "today": "22 Sep 2026",
        "count": 2, "base": opt("https://grc.example"),
        "groups": [("high", [{"title": "Access policy", "detail": "Review overdue", "to": opt("/documents/1")}]),
                   ("low", [{"title": "Backup test", "detail": "Due in 5 days", "to": ""}])],
        "vendor": ns(name="Northwind", contact_email=opt("sec@northwind.example"),
                     get_tier_display="High", data_handled=opt("Customer PII")),
        "report": ns(get_kind_display="SOC 2 Type II"), "lapsed_on": "1 Sep 2026", "days": 3 if on else 1,
        "request": ns(reference="PBC-1", title="Access review", control_ref=opt("CC6.1"),
                      due_date="30 Sep 2026", requested_by_name="Ann", get_requested_by_side_display="Auditor",
                      description=opt("Q3 export"), status="returned" if on else "open",
                      returned_note=opt("Wrong quarter")),
        "package": ns(name="SOC 2 2026", audit_firm=opt("Example LLP")), "overdue": on,
        "questions": [1, 2], "message": opt("Thanks for your help."), "link": "https://grc.example/q/abc",
        "deadline": "1 Oct 2026",
        "invite": ns(respondent_name="Rita", respondent_title=opt("CISO"), sent_to="rita@northwind.example"),
        "answered": 2, "total": 2, "noes": 1 if on else 0,
        "document": ns(name="Access policy", get_review_cadence_display="Annual", next_review_date="1 Oct 2026"),
        "folder_path": "Policies / Access", "down": on, "since": "09:00 UTC",
    }


class EmailCopyTests(SimpleTestCase):
    """What a recipient reads, in both parts of every email. The 0.9.5j dash
    sweep turned "&mdash; Conformiti" into ", Conformiti" and "request &mdash;
    please" into "request , please", and nothing rendered the templates."""

    EMAILS = Path(__file__).resolve().parent / "templates" / "emails"
    # Block tags break a line where the mail client would; inline ones do not.
    BLOCK_TAG = re.compile(r"<(?:br|/?(?:p|div|li|ul|ol|h[1-6]|tr|td|th|table|blockquote|pre|body|html))\b[^>]*>", re.I)
    ANY_TAG = re.compile(r"<[^>]+>")

    def _lines(self, name, body):
        if name.endswith(".html"):
            body = html.unescape(self.ANY_TAG.sub("", self.BLOCK_TAG.sub("\n", body)))
        return body.splitlines()

    def test_no_email_line_opens_with_a_comma_or_carries_a_dash(self):
        names = sorted(p.name for p in self.EMAILS.iterdir() if p.suffix in (".html", ".txt"))
        self.assertTrue(names)
        for name in names:
            for on in (True, False):
                with self.subTest(template=name, optional_parts=on):
                    for line in self._lines(name, render_to_string(f"emails/{name}", _email_context(on))):
                        self.assertFalse(line.strip().startswith(","), line)
                        self.assertNotIn(" ,", line)
                        self.assertNotRegex(line, "[\u2013\u2014]")
                        # "--" standing in for a dash, as the old plain-text sign-offs had it
                        self.assertNotRegex(line, r"(?:^|\s)--(?:\s|$)")
