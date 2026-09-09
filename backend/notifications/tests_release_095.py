"""0.9.5: a reminder is claimed in the database before it is sent, so two
scans running at once cannot both send it; and chat channels belong to the
workspace on an installation with several."""
from unittest import mock

from django.test import override_settings

from accounts import tenancy
from accounts.models import Workspace
from documents.models import Document
from notifications import webhooks
from notifications.tasks import OVERDUE, run_review_scan
from testutils import APITestBase, make_doc


class ClaimBeforeSendTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Policy", days=-2)

    def test_the_window_is_recorded_before_the_mail_goes_out(self):
        """Two workers read "not sent"; only the one whose conditional UPDATE
        matches gets to send. The property that makes that safe is that the
        claim is durable before the send starts."""
        seen = {}

        def spy(doc, days, overdue=False, window=None):
            seen["at_send"] = Document.objects.get(pk=doc.pk).reminders_sent

        with mock.patch("notifications.tasks._notify", side_effect=spy):
            self.assertEqual(run_review_scan(), 1)
        self.assertEqual(seen["at_send"], [OVERDUE])

    def test_a_row_another_worker_claimed_is_not_sent_again(self):
        # Worker B got there first: the row already says overdue was sent.
        Document.objects.filter(pk=self.doc.pk).update(reminders_sent=[OVERDUE])
        with mock.patch("notifications.tasks._notify") as sent:
            self.assertEqual(run_review_scan(), 0)
        sent.assert_not_called()

    def test_a_failed_send_hands_the_claim_back(self):
        with mock.patch("notifications.tasks._notify", side_effect=RuntimeError("smtp down")):
            self.assertEqual(run_review_scan(), 0)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.reminders_sent, [], "the next run must retry it")
        self.assertNotEqual(self.doc.status, Document.Status.EXPIRED)
        with mock.patch("notifications.tasks._notify") as sent:
            self.assertEqual(run_review_scan(), 1)
        sent.assert_called_once()

    def test_dry_run_claims_nothing(self):
        self.assertEqual(run_review_scan(dry_run=True), 1)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.reminders_sent, [])


@override_settings(SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T/B/installation",
                   TEAMS_WEBHOOK_URL="")
class WorkspaceChannelTests(APITestBase):
    """One installation-wide webhook used to receive every organisation's
    sealed packages and auditor requests, each prefixed with the
    organisation's name — a disclosure to every other organisation reading
    the channel."""

    def test_a_single_workspace_installation_uses_the_installation_channel(self):
        self.assertEqual(webhooks.channels(), [("slack", "https://hooks.slack.com/services/T/B/installation")])

    def test_with_several_workspaces_a_tenant_event_goes_only_to_its_own_channel(self):
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-ltd",
                                        slack_webhook_url="https://hooks.slack.com/services/T/B/beta")
        # The default workspace configured nothing of its own: its events go
        # nowhere rather than to the shared channel.
        self.assertEqual(webhooks.channels(), [])
        with tenancy.scoped(beta):
            self.assertEqual(webhooks.channels(), [("slack", "https://hooks.slack.com/services/T/B/beta")])
        # An installation-level event (nothing active) still reaches the operator.
        with tenancy.unscoped():
            self.assertEqual(webhooks.channels(),
                             [("slack", "https://hooks.slack.com/services/T/B/installation")])

    @override_settings(WEBHOOKS_SHARED_ACROSS_WORKSPACES=True)
    def test_the_shared_channel_can_be_chosen_deliberately(self):
        Workspace.objects.create(name="Beta Ltd", slug="beta-ltd")
        self.assertEqual(webhooks.channels(),
                         [("slack", "https://hooks.slack.com/services/T/B/installation")])

    def test_the_settings_screen_is_told_where_the_channels_come_from(self):
        Workspace.objects.create(name="Beta Ltd", slug="beta-ltd")
        r = self.client_for(self.admin).get("/api/notifications/channels/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["slack"])
        self.assertEqual(r.data["source"], "none")
        self.assertTrue(r.data["multi_workspace"])
        self.assertEqual(r.data["installation_channels"], ["slack"])

    def test_a_workspace_webhook_must_be_https_and_on_the_right_host(self):
        client = self.client_for(self.admin)
        ws = Workspace.objects.get(slug="default")
        bad = client.patch(f"/api/workspaces/{ws.pk}/",
                           {"slack_webhook_url": "http://hooks.slack.com/x"}, format="json")
        self.assertEqual(bad.status_code, 400)
        wrong_host = client.patch(f"/api/workspaces/{ws.pk}/",
                                  {"slack_webhook_url": "https://example.com/x"}, format="json")
        self.assertEqual(wrong_host.status_code, 400)
        good = client.patch(f"/api/workspaces/{ws.pk}/",
                            {"slack_webhook_url": "https://hooks.slack.com/services/T/B/ws",
                             "teams_webhook_url": ""}, format="json")
        self.assertEqual(good.status_code, 200, good.data)
        self.assertEqual(webhooks.channels(), [("slack", "https://hooks.slack.com/services/T/B/ws")])
        self.assertEqual(self.client_for(self.manager).patch(
            f"/api/workspaces/{ws.pk}/", {"slack_webhook_url": ""}, format="json").status_code, 403)
