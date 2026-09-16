"""The third-party review of 0.9.5, fixed in 0.9.5b (REVIEW_095.md).

S-1 webhook URLs readable by every role · S-2 the host allow-list and the
redirect-following request · S-3 encryption at rest · S-5 the mailed link's
base · S-6 the SAML attributes that were optional · S-7 the sign-out that
could not see the refresh cookie.

S-4 lives in ``documents.tests_uploads`` with the rest of upload validation,
and S-8 in ``attestations.tests_review_fixes`` beside the check it changes.
"""
import urllib.error
from unittest import mock

from django.test import override_settings

from accounts.models import Workspace
from config import outbound
from notifications import webhooks
from notifications.models import WebhookDelivery
from testutils import APITestBase

SLACK = "https://hooks.slack.com/services/T000/B000/secret"
PUBLIC_ADDRESS = [(2, 1, 6, "", ("93.184.216.34", 443))]


def stub_dns(case, addresses=PUBLIC_ADDRESS):
    patcher = mock.patch("config.outbound.socket.getaddrinfo", return_value=addresses)
    patcher.start()
    case.addCleanup(patcher.stop)


class WebhookSecrecyTests(APITestBase):
    """S-1. An incoming-webhook URL is a credential: whoever holds it can post
    into the channel as the app. 0.9.5 returned both of them on a read every
    signed-in account could make, the issued external auditor included."""

    def setUp(self):
        super().setUp()
        workspace = Workspace.objects.get(pk=self.admin.workspace_id)
        workspace.slack_webhook_url = SLACK
        workspace.save()

    def test_nobody_reads_a_webhook_back_not_even_the_superuser(self):
        for user in (self.admin, self.manager, self.owner, self.viewer, self.auditor):
            for url in ("/api/workspaces/current/", f"/api/workspaces/{self.admin.workspace_id}/"):
                r = self.client_for(user).get(url)
                if r.status_code == 404:      # not everyone may retrieve by id
                    continue
                self.assertEqual(r.status_code, 200, (user.username, url))
                self.assertNotIn("hooks.slack.com", str(r.data), (user.username, url))
                self.assertNotIn("secret", str(r.data), (user.username, url))

    def test_the_operator_is_told_a_channel_is_configured_without_being_told_which(self):
        r = self.client_for(self.admin).get("/api/workspaces/current/")
        self.assertTrue(r.data["slack_configured"])
        self.assertFalse(r.data["teams_configured"])

    def test_everyone_else_gets_the_name_and_nothing_about_the_organisation(self):
        for user in (self.manager, self.owner, self.viewer, self.auditor):
            r = self.client_for(user).get("/api/workspaces/current/")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data["name"], "Default")
            for key in ("notification_email", "slack_configured", "teams_configured", "users"):
                self.assertNotIn(key, r.data, (user.username, key))

    def test_saving_the_reminder_address_leaves_a_configured_channel_alone(self):
        """The settings form cannot read the URL back, so it sends the field
        only when someone typed one. A PATCH without it must not clear it."""
        client = self.client_for(self.admin)
        r = client.patch(f"/api/workspaces/{self.admin.workspace_id}/",
                         {"notification_email": "grc@example.com"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Workspace.objects.get(pk=self.admin.workspace_id).slack_webhook_url, SLACK)
        self.assertTrue(client.get("/api/workspaces/current/").data["slack_configured"])

    def test_and_an_empty_string_still_removes_it_deliberately(self):
        client = self.client_for(self.admin)
        r = client.patch(f"/api/workspaces/{self.admin.workspace_id}/",
                         {"slack_webhook_url": ""}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Workspace.objects.get(pk=self.admin.workspace_id).slack_webhook_url, "")


class WebhookDestinationTests(APITestBase):
    """S-2. ``"hooks.slack.com" in url`` is not a host check, and a request
    that follows redirects has no host at all by the time it arrives."""

    SPOOFS = [
        "https://hooks.slack.com.attacker.example/x",   # a longer name
        "https://attacker.example/?hooks.slack.com",    # in the query
        "https://attacker.example/#hooks.slack.com",    # in the fragment
        "https://hooks.slack.com@attacker.example/",    # userinfo
        "https://hooks.slack.com:8443/services/x",      # a port of its own
        "http://hooks.slack.com/services/x",            # not https
    ]

    def test_the_api_refuses_every_way_of_spelling_someone_elses_host(self):
        client = self.client_for(self.admin)
        for url in self.SPOOFS:
            r = client.patch(f"/api/workspaces/{self.admin.workspace_id}/",
                             {"slack_webhook_url": url}, format="json")
            self.assertEqual(r.status_code, 400, url)
        self.assertEqual(Workspace.objects.get(pk=self.admin.workspace_id).slack_webhook_url, "")

    def test_a_teams_webhook_must_be_on_a_teams_host(self):
        client = self.client_for(self.admin)
        self.assertEqual(client.patch(
            f"/api/workspaces/{self.admin.workspace_id}/",
            {"teams_webhook_url": "https://attacker.example/hook"}, format="json").status_code, 400)
        self.assertEqual(client.patch(
            f"/api/workspaces/{self.admin.workspace_id}/",
            {"teams_webhook_url": "https://x.webhook.office.com/webhookb2/a"},
            format="json").status_code, 200)

    def test_the_admin_cannot_store_what_the_api_refuses(self):
        """The Django admin never runs a serializer, which is why the same
        rule is on the model."""
        from django.core.exceptions import ValidationError

        workspace = Workspace.objects.get(pk=self.admin.workspace_id)
        workspace.slack_webhook_url = "https://169.254.169.254/latest/meta-data/"
        with self.assertRaises(ValidationError):
            workspace.full_clean()

    @override_settings(WEBHOOK_SYNC=True, NOTIFY_EVENTS=[])
    def test_a_stored_url_is_checked_again_before_every_post(self):
        """A value can reach the column another way: a fixture, a restored
        backup, a release older than this rule."""
        Workspace.objects.filter(pk=self.admin.workspace_id).update(
            slack_webhook_url="https://redis.internal/x")
        stub_dns(self)
        with mock.patch("notifications.webhooks._open") as sender:
            webhooks.post_event("test", "x", "y", sync=True)
        sender.assert_not_called()
        row = WebhookDelivery.objects.get(channel="slack")
        self.assertFalse(row.ok)
        self.assertIn("refused", row.error)

    @override_settings(WEBHOOK_SYNC=True, NOTIFY_EVENTS=[])
    def test_a_redirect_is_refused_rather_than_followed(self):
        Workspace.objects.filter(pk=self.admin.workspace_id).update(slack_webhook_url=SLACK)
        stub_dns(self)
        bounced = outbound.OutboundError("redirect", "The endpoint attempted a redirect.")
        with mock.patch("notifications.webhooks._open", side_effect=bounced):
            webhooks.post_event("test", "x", "y", sync=True)
        row = WebhookDelivery.objects.get(channel="slack")
        self.assertFalse(row.ok)
        self.assertIn("redirect", row.error)

    @override_settings(WEBHOOK_SYNC=True, NOTIFY_EVENTS=[])
    def test_a_name_that_resolves_inside_the_network_is_refused(self):
        """The check that matters: the host passes the allow-list and still
        answers with a private address."""
        Workspace.objects.filter(pk=self.admin.workspace_id).update(slack_webhook_url=SLACK)
        stub_dns(self, [(2, 1, 6, "", ("169.254.169.254", 443))])
        with mock.patch("notifications.webhooks._open") as sender:
            webhooks.post_event("test", "x", "y", sync=True)
        sender.assert_not_called()
        self.assertIn("public address", WebhookDelivery.objects.get(channel="slack").error)

    def test_every_answer_must_be_public_not_merely_the_first(self):
        stub_dns(self, [(2, 1, 6, "", ("93.184.216.34", 443)),
                        (2, 1, 6, "", ("127.0.0.1", 443))])
        with self.assertRaises(outbound.OutboundError):
            outbound.assert_safe_url(SLACK, allowed_hosts=["hooks.slack.com"])


class WebhookAtRestTests(APITestBase):
    """S-3. The column holds an envelope, not the URL."""

    def test_the_stored_column_is_ciphertext_and_reads_back_as_the_url(self):
        workspace = Workspace.objects.get(pk=self.admin.workspace_id)
        workspace.slack_webhook_url = SLACK
        workspace.save()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT slack_webhook_url FROM accounts_workspace WHERE id = %s",
                           [workspace.pk])
            stored = cursor.fetchone()[0]
        self.assertTrue(stored.startswith("fc1$"), stored[:20])
        self.assertNotIn("hooks.slack.com", stored)
        self.assertEqual(Workspace.objects.get(pk=workspace.pk).slack_webhook_url, SLACK)

    def test_a_workspace_created_with_a_webhook_already_set_keeps_it(self):
        """The envelope is bound to the row id, which does not exist until the
        insert lands. Creating a workspace with a webhook filled in is a real
        path: the admin's add form does exactly that."""
        created = Workspace.objects.create(name="Beta Ltd", slug="beta-ltd",
                                           slack_webhook_url=SLACK)
        self.assertEqual(Workspace.objects.get(pk=created.pk).slack_webhook_url, SLACK)

    def test_an_envelope_moved_between_organisations_does_not_decrypt(self):
        """What binding to the row id buys: a ciphertext lifted out of one
        organisation's row reads as empty in another's, rather than handing
        over a working channel."""
        from django.db import connection

        first = Workspace.objects.get(pk=self.admin.workspace_id)
        first.slack_webhook_url = SLACK
        first.save()
        second = Workspace.objects.create(name="Beta Ltd", slug="beta-ltd")
        with connection.cursor() as cursor:
            cursor.execute("SELECT slack_webhook_url FROM accounts_workspace WHERE id = %s",
                           [first.pk])
            envelope = cursor.fetchone()[0]
            cursor.execute("UPDATE accounts_workspace SET slack_webhook_url = %s WHERE id = %s",
                           [envelope, second.pk])
        self.assertEqual(Workspace.objects.get(pk=second.pk).slack_webhook_url, "")


class KeyRotationCoverageTests(APITestBase):
    """Not in the review, found while fixing S-3.

    The rotation command carried a hand-written list of encrypted columns and
    a comment asking the next person to extend it. Encrypting the two webhook
    columns without extending it would have left them on the old key, and
    step 3 of a key rotation (drop the old key) would then have made every
    stored webhook unreadable. It now asks the model registry instead.
    """

    def test_every_encrypted_column_is_rotated(self):
        from accounts.management.commands.rotate_field_keys import encrypted_columns

        found = {(m._meta.db_table, f.column) for m, f in encrypted_columns()}
        for column in ("slack_webhook_url", "teams_webhook_url"):
            self.assertIn(("accounts_workspace", column), found)
        self.assertIn(("accounts_mfadevice", "secret"), found)
        self.assertIn(("integrations_jiraintegration", "api_token"), found)

    def test_rotation_moves_a_webhook_onto_the_new_key_and_it_still_reads(self):
        from io import StringIO

        from django.conf import settings
        from django.core.management import call_command

        from config import fieldcrypto

        workspace = Workspace.objects.get(pk=self.admin.workspace_id)
        workspace.slack_webhook_url = SLACK
        workspace.save()
        newest = "a-new-key-" + "x" * 40
        with override_settings(
                FIELD_ENCRYPTION_KEYS=[newest] + list(settings.FIELD_ENCRYPTION_KEYS)):
            call_command("rotate_field_keys", stdout=StringIO(), stderr=StringIO())
            self.assertEqual(Workspace.objects.get(pk=workspace.pk).slack_webhook_url, SLACK)
            # Read the column itself: the descriptor caches the plaintext back
            # onto the instance once the attribute has been touched.
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute("SELECT slack_webhook_url FROM accounts_workspace WHERE id = %s",
                               [workspace.pk])
                stored = cursor.fetchone()[0]
            self.assertEqual(fieldcrypto.envelope_key_id(stored), fieldcrypto.key_ids()[0])


class QuestionnaireLinkBaseTests(APITestBase):
    """S-5. The token in a questionnaire link is a bearer credential, so the
    host it points at cannot come from the request that asked for it."""

    @override_settings(DEBUG=False, PUBLIC_URL="")
    def test_off_debug_an_unset_public_url_refuses_rather_than_guesses(self):
        from vendors import questionnaire

        with self.assertRaises(questionnaire.LinkBaseUnset):
            questionnaire.public_base(None)

    @override_settings(DEBUG=False, PUBLIC_URL="https://grc.example")
    def test_public_url_decides_it(self):
        from vendors import questionnaire

        self.assertEqual(questionnaire.public_base(None), "https://grc.example")

    @override_settings(DEBUG=True, PUBLIC_URL="",
                       CSRF_TRUSTED_ORIGINS=["http://localhost:5173"])
    def test_in_debug_only_an_origin_the_operator_already_named_is_accepted(self):
        from django.test import RequestFactory

        from vendors import questionnaire

        factory = RequestFactory()
        named = factory.post("/", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(questionnaire.public_base(named), "http://localhost:5173")
        spoofed = factory.post("/", HTTP_ORIGIN="https://phish.example")
        self.assertNotIn("phish.example", questionnaire.public_base(spoofed))


class SignOutTests(APITestBase):
    """S-7. The refresh cookie's path is /api/auth/token/, so a sign-out
    anywhere else never receives it."""

    @override_settings(AUTH_TRANSPORT="cookie")
    def test_the_token_path_sign_out_revokes_the_refresh_token(self):
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken, OutstandingToken,
        )
        from rest_framework_simplejwt.tokens import RefreshToken

        from accounts import cookie_auth

        refresh = RefreshToken.for_user(self.manager)
        client = self.client_for()
        client.cookies[cookie_auth.refresh_cookie_name()] = str(refresh)
        # No access cookie at all: the case the endpoint exists for.
        r = client.post("/api/auth/token/clear/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["revoked"], 1)
        token = OutstandingToken.objects.get(jti=refresh["jti"])
        self.assertTrue(BlacklistedToken.objects.filter(token=token).exists())

    @override_settings(AUTH_TRANSPORT="cookie")
    def test_the_old_endpoint_still_answers_for_an_older_client(self):
        r = self.client_for().post("/api/auth/session/clear/", {}, format="json")
        self.assertEqual(r.status_code, 200)


# S-6 is tested in ``tests_saml``, against the signed-assertion harness that
# already lives there: a response naming no destination, and a bearer
# confirmation naming no recipient.
