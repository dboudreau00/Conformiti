"""Slack / Teams webhooks and the emailed digest."""
import json
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from attestations.tests import PackageTestBase
from notifications import webhooks
from notifications.models import NotificationReceipt, WebhookDelivery
from notifications.tasks import post_daily_summary, run_digests
from testutils import APITestBase, make_doc

CHANNELS = dict(SLACK_WEBHOOK_URL="https://hooks.slack.test/T/B/x", TEAMS_WEBHOOK_URL="https://teams.test/hook",
                WEBHOOK_SYNC=True, PUBLIC_URL="https://grc.example", NOTIFY_EVENTS=[])


class FakeUrlopen:
    """Records every POST and answers 200 (or what ``status`` says)."""

    def __init__(self, status=200):
        self.calls = []
        self.status = status

    def __call__(self, request, timeout=None):
        self.calls.append({"url": request.full_url, "body": json.loads(request.data.decode("utf-8")),
                           "headers": dict(request.header_items()), "timeout": timeout})
        fake = mock.MagicMock()
        fake.__enter__.return_value.status = self.status
        return fake


@override_settings(**CHANNELS)
class WebhookTests(PackageTestBase):
    def setUp(self):
        super().setUp()
        self.http = FakeUrlopen()
        self.patcher = mock.patch("urllib.request.urlopen", self.http)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_payloads_fit_each_service_and_carry_the_link(self):
        attempted = webhooks.post_event("test", "Hello", "Body text", facts=[("Key", "Value")],
                                        path="/packages", severity="high", sync=True)
        self.assertEqual(attempted, ["slack", "teams"])
        by_url = {c["url"]: c["body"] for c in self.http.calls}
        slack = by_url["https://hooks.slack.test/T/B/x"]
        self.assertIn(":warning: *Hello*", slack["blocks"][0]["text"]["text"])
        self.assertIn("https://grc.example/packages", slack["blocks"][-1]["elements"][0]["text"])
        teams = by_url["https://teams.test/hook"]
        card = teams["attachments"][0]["content"]
        self.assertEqual(card["type"], "AdaptiveCard")
        self.assertEqual(card["body"][0]["text"], "Hello")
        self.assertEqual(card["body"][2]["facts"], [{"title": "Key", "value": "Value"}])
        self.assertEqual(card["actions"][0]["url"], "https://grc.example/packages")
        self.assertEqual(self.http.calls[0]["headers"]["Content-type"], "application/json")
        self.assertEqual(WebhookDelivery.objects.filter(ok=True).count(), 2)

    def test_https_only_and_the_allow_list(self):
        with override_settings(SLACK_WEBHOOK_URL="http://hooks.slack.test/plain"):
            webhooks.post_event("test", "x", "y", sync=True)
        refused = WebhookDelivery.objects.get(channel="slack")
        self.assertFalse(refused.ok)
        self.assertIn("not https", refused.error)
        self.assertEqual(len(self.http.calls), 1)          # Teams still got it
        with override_settings(NOTIFY_EVENTS=["package.sealed"]):
            self.assertEqual(webhooks.post_event("pbc.returned", "x", "y", sync=True), [])
            self.assertEqual(webhooks.post_event("package.sealed", "x", "y", sync=True), ["slack", "teams"])
        with override_settings(SLACK_WEBHOOK_URL="", TEAMS_WEBHOOK_URL=""):
            self.assertEqual(webhooks.post_event("package.sealed", "x", "y", sync=True), [])

    def test_a_failing_endpoint_is_recorded_and_never_breaks_the_caller(self):
        import urllib.error
        self.http.status = 500
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            self.assertEqual(webhooks.post_event("test", "x", "y", sync=True), ["slack", "teams"])
        rows = WebhookDelivery.objects.all()
        self.assertEqual(rows.count(), 2)
        self.assertTrue(all(not r.ok and "refused" in r.error for r in rows))

    def test_sealing_issuing_and_withdrawing_post(self):
        self.add_control()
        self.seal()
        self.assertEqual({c["body"].get("text", "")[:15] for c in self.http.calls if "text" in c["body"]},
                         {"Package sealed:"})
        self.issue_to(self.auditor)
        self.assertEqual(WebhookDelivery.objects.filter(event="package.issued").count(), 2)
        self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/withdraw/", {"reason": "done"}, format="json")
        self.assertEqual(WebhookDelivery.objects.filter(event="package.withdrawn").count(), 2)

    def test_the_auditors_return_and_raise_post_but_the_organisations_do_not(self):
        self.add_control()
        self.seal()
        self.issue_to(self.auditor)
        auditor = self.client_for(self.auditor)
        line = auditor.post("/api/pbc-requests/", {"package": self.package.pk, "title": "Leaver list"}, format="json").data
        self.assertEqual(WebhookDelivery.objects.filter(event="pbc.raised").count(), 2)
        self.manager_client.post("/api/pbc-requests/", {"package": self.package.pk, "title": "Transcribed"}, format="json")
        self.assertEqual(WebhookDelivery.objects.filter(event="pbc.raised").count(), 2)
        self.manager_client.post(f"/api/pbc-requests/{line['id']}/provide/", {"response_note": "x"}, format="json")
        auditor.post(f"/api/pbc-requests/{line['id']}/return/", {"returned_note": "Need FY, not Q1"}, format="json")
        self.assertEqual(WebhookDelivery.objects.filter(event="pbc.returned").count(), 2)
        self.assertIn("Need FY, not Q1", json.dumps(self.http.calls[-1]["body"]))

    def test_the_channels_endpoint_and_the_test_message(self):
        info = self.client_for(self.viewer).get("/api/notifications/channels/").data
        self.assertEqual((info["slack"], info["teams"]), (True, True))
        self.assertNotIn("deliveries", info)
        self.assertEqual(self.client_for(self.viewer).post("/api/notifications/channels/", {}, format="json").status_code, 403)
        r = self.client_for(self.admin).post("/api/notifications/channels/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["attempted"], ["slack", "teams"])
        self.assertTrue(all(x["ok"] for x in r.data["results"]))
        admin_view = self.client_for(self.admin).get("/api/notifications/channels/").data
        self.assertEqual(len(admin_view["deliveries"]), 2)
        with override_settings(SLACK_WEBHOOK_URL="", TEAMS_WEBHOOK_URL=""):
            self.assertEqual(self.client_for(self.admin).post("/api/notifications/channels/", {}, format="json").status_code, 400)

    def test_the_daily_summary_posts_only_when_something_is_outstanding(self):
        self.assertEqual(post_daily_summary(), [])
        make_doc(self.tree.ctrl1, self.owner, name="Late", days=-2)
        self.assertEqual(post_daily_summary(), ["slack", "teams"])
        self.assertIn("Documents overdue for review", json.dumps(self.http.calls[-1]["body"]))


@override_settings(EMAIL_PROVIDER="console", PUBLIC_URL="https://grc.example")
class DigestTests(APITestBase):
    def test_the_preference_is_the_persons_own_and_the_digest_follows_it(self):
        c = self.client_for(self.owner)
        self.assertEqual(c.get("/api/users/me/").data["digest"], "off")
        self.assertEqual(c.patch("/api/users/me/", {"digest": "daily"}, format="json").data["digest"], "daily")
        self.assertEqual(c.patch("/api/users/me/", {"digest": "hourly"}, format="json").status_code, 400)
        make_doc(self.tree.ctrl1, self.owner, name="Late policy", days=-3)
        make_doc(self.tree.ctrl1, self.owner, name="Soon policy", days=5)
        # Nobody else asked; Owen gets one email with both items, once per day.
        self.assertEqual(run_digests(dry_run=True), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(run_digests(), 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["owen@test.local"])
        self.assertIn("2 items need your attention", message.subject)
        self.assertIn("Review overdue: Late policy", message.body)
        self.assertIn("https://grc.example/documents", message.body)
        self.assertEqual(run_digests(), 0)
        # Tomorrow it goes again; a dismissed item stays out.
        self.owner.refresh_from_db()
        self.owner.digest_sent_at = timezone.now() - timezone.timedelta(days=1)
        self.owner.save()
        doc = self.owner.owned_documents.get(name="Soon policy")
        NotificationReceipt.objects.create(user=self.owner, key=f"doc-due:{doc.pk}", dismissed_at=timezone.now())
        self.assertEqual(run_digests(), 1)
        self.assertNotIn("Soon policy", mail.outbox[1].body)
        self.assertIn("1 item need", mail.outbox[1].subject)

    def test_weekly_goes_on_mondays_and_an_empty_tray_sends_nothing(self):
        from datetime import date
        self.viewer.digest = "weekly"
        self.viewer.save()
        self.owner.digest = "daily"
        self.owner.save()
        make_doc(self.tree.ctrl1, self.owner, name="Late", days=-1)
        tuesday, monday = date(2026, 9, 8), date(2026, 9, 7)
        # Val (weekly, empty tray) never gets one, Monday or not; Owen gets his.
        self.assertEqual(run_digests(today=tuesday), 1)
        self.assertEqual([m.to for m in mail.outbox], [["owen@test.local"]])
        self.owner.digest = "off"
        self.owner.save()
        self.assertEqual(run_digests(today=monday), 0)
        # A weekly person with something in the tray gets it on Monday only.
        make_doc(self.tree.ctrl1, self.viewer, name="Val's late doc", days=-1)
        self.assertEqual(run_digests(today=tuesday), 0)
        self.assertEqual(run_digests(today=monday), 1)
        self.assertEqual(mail.outbox[-1].to, ["val@test.local"])

    def test_the_command_reports(self):
        out = StringIO()
        call_command("send_digests", "--dry-run", stdout=out)
        self.assertIn("Digests would be sent: 0", out.getvalue())
