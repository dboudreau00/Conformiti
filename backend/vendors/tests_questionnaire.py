"""The questionnaire sent to the vendor: issuing the link, what the link can
and cannot do, submission into a pending assessment, and the feed."""
import re

from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditLog
from notifications.notifications import build as build_feed
from testutils import APITestBase
from vendors.models import QuestionnaireInvite, Vendor, VendorAssessment


def _vendor(**extra):
    defaults = dict(name="Northwind Cloud", category="Cloud hosting", tier="critical",
                    contact_email="security@northwind.example")
    defaults.update(extra)
    return Vendor.objects.create(**defaults)


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local",
                   ORGANISATION_NAME="Acme Ltd", PUBLIC_URL="https://grc.acme.example")
class SendTests(APITestBase):
    def send(self, vendor, **body):
        return self.client_for(self.manager).post(
            f"/api/vendors/{vendor.pk}/questionnaire/send/", body, format="json")

    def test_sending_emails_a_link_and_returns_it_once(self):
        v = _vendor(owner=self.owner)
        r = self.send(v, message="Please answer before the audit.")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["link"].startswith("https://grc.acme.example/questionnaire/"))
        self.assertEqual(r.data["sent_to"], "security@northwind.example")
        self.assertEqual(r.data["status"], "open")
        self.assertTrue(r.data["email_sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["security@northwind.example"])
        self.assertIn(r.data["link"], mail.outbox[0].body)
        self.assertIn("Please answer before the audit.", mail.outbox[0].body)
        self.assertIn("Acme Ltd", mail.outbox[0].subject)
        # The token is never stored or listed; only its hash is.
        token = r.data["link"].rsplit("/", 1)[1]
        self.assertNotIn(token, str(QuestionnaireInvite.objects.values()))
        listed = self.client_for(self.manager).get(f"/api/vendors/{v.pk}/questionnaire/invites/").data
        self.assertEqual(len(listed), 1)
        self.assertNotIn("link", listed[0])
        self.assertNotIn("token_hash", listed[0])
        self.assertTrue(AuditLog.objects.filter(object_type="vendor-questionnaire",
                                                detail__contains="questionnaire sent to").exists())

    def test_a_recipient_and_a_sane_window_are_required(self):
        v = _vendor(contact_email="")
        self.assertEqual(self.send(v).status_code, 400)
        self.assertEqual(self.send(v, email="not-an-email").status_code, 400)
        self.assertEqual(self.send(v, email="a@b.example", days=0).status_code, 400)
        self.assertEqual(self.send(v, email="a@b.example", days=400).status_code, 400)
        ok = self.send(v, email="a@b.example", days=30)
        self.assertEqual(ok.status_code, 201)
        window = QuestionnaireInvite.objects.get().expires_at - timezone.now()
        self.assertAlmostEqual(window.days, 29, delta=1)

    def test_a_second_send_supersedes_the_first_and_only_the_frameworks_capability_sends(self):
        v = _vendor()
        first = self.send(v).data["link"].rsplit("/", 1)[1]
        second = self.send(v).data["link"].rsplit("/", 1)[1]
        self.assertEqual(APIClient().get(f"/api/questionnaire/{first}/").data["status"], "revoked")
        self.assertEqual(APIClient().get(f"/api/questionnaire/{second}/").data["status"], "open")
        for who in (self.viewer, self.owner, self.auditor):
            r = self.client_for(who).post(f"/api/vendors/{v.pk}/questionnaire/send/", {}, format="json")
            self.assertEqual(r.status_code, 403, who.username)

    def test_revoking_closes_the_link(self):
        v = _vendor()
        r = self.send(v)
        token = r.data["link"].rsplit("/", 1)[1]
        self.assertEqual(self.client_for(self.manager).post(
            f"/api/questionnaire-invites/{r.data['id']}/revoke/").data["status"], "revoked")
        anon = APIClient()
        self.assertEqual(anon.get(f"/api/questionnaire/{token}/").data["status"], "revoked")
        self.assertEqual(anon.put(f"/api/questionnaire/{token}/", {"answers": {}}, format="json").status_code, 400)
        self.assertEqual(anon.post(f"/api/questionnaire/{token}/submit/",
                                   {"answers": {"soc2": {"answer": "yes"}}, "respondent_name": "X"},
                                   format="json").data["code"], "revoked")


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local")
class VendorSideTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.vendor = _vendor(owner=self.owner)
        r = self.client_for(self.manager).post(
            f"/api/vendors/{self.vendor.pk}/questionnaire/send/", {}, format="json")
        self.token = r.data["link"].rsplit("/", 1)[1]
        self.invite = QuestionnaireInvite.objects.get(pk=r.data["id"])
        mail.outbox.clear()
        self.anon = APIClient()

    def test_the_link_shows_the_questions_and_nothing_else_about_us(self):
        r = self.anon.get(f"/api/questionnaire/{self.token}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["vendor"], "Northwind Cloud")
        self.assertEqual(r.data["status"], "open")
        self.assertEqual(len(r.data["questions"]), 12)
        self.assertEqual(r.data["answers"], {})
        self.assertNotIn("tier", r.data)
        self.assertNotIn("owner", r.data)
        self.invite.refresh_from_db()
        self.assertIsNotNone(self.invite.opened_at)
        # An unknown token is a 404, not a hint.
        self.assertEqual(self.anon.get("/api/questionnaire/nope/").status_code, 404)
        self.assertEqual(self.anon.get(f"/api/questionnaire/{self.token[:-1]}x/").status_code, 404)

    def test_drafts_save_with_validation_and_come_back(self):
        r = self.anon.put(f"/api/questionnaire/{self.token}/",
                          {"answers": {"soc2": {"answer": "yes", "note": "Report attached separately"}}},
                          format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.anon.get(f"/api/questionnaire/{self.token}/").data["answers"]["soc2"]["note"],
                         "Report attached separately")
        bad = self.anon.put(f"/api/questionnaire/{self.token}/",
                            {"answers": {"made_up": {"answer": "yes"}}}, format="json")
        self.assertEqual(bad.status_code, 400)
        bad = self.anon.put(f"/api/questionnaire/{self.token}/",
                            {"answers": {"soc2": {"answer": "maybe"}}}, format="json")
        self.assertEqual(bad.status_code, 400)
        # Nothing was filed against the vendor by saving a draft.
        self.assertFalse(VendorAssessment.objects.exists())

    def test_submitting_files_a_pending_assessment_notifies_and_closes_the_link(self):
        body = {"answers": {"soc2": {"answer": "yes"}, "pentest": {"answer": "no", "note": "Planned Q4"},
                            "dpa": {"answer": "partial"}},
                "respondent_name": "Nia Northwind", "respondent_title": "CISO"}
        r = self.anon.post(f"/api/questionnaire/{self.token}/submit/", body, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "submitted")
        a = VendorAssessment.objects.get()
        self.assertEqual((a.kind, a.result, a.vendor_id), ("questionnaire", "pending", self.vendor.pk))
        self.assertEqual(a.answers["pentest"], {"answer": "no", "note": "Planned Q4"})
        self.assertIn("Nia Northwind (CISO)", a.findings)
        self.assertIn("3 of 12", a.findings)
        self.assertIsNone(a.reviewed_by)
        self.invite.refresh_from_db()
        self.assertEqual(self.invite.assessment_id, a.pk)
        self.assertEqual(self.invite.respondent_name, "Nia Northwind")
        # The owner, the sender and the team hear about it.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(set(mail.outbox[0].to), {"owen@test.local", "mia@test.local", "grc@test.local"})
        self.assertIn("returned their security questionnaire", mail.outbox[0].subject)
        self.assertIn("3 of 12", mail.outbox[0].body)
        # Second submission of the same link is refused; the draft is read-only.
        r = self.anon.post(f"/api/questionnaire/{self.token}/submit/", body, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "submitted")
        self.assertEqual(self.anon.get(f"/api/questionnaire/{self.token}/").data["status"], "submitted")
        self.assertEqual(VendorAssessment.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(object_type="vendor-questionnaire", user__isnull=True,
                                                detail__contains="submitted by Nia Northwind").exists())

    def test_submission_needs_a_name_and_an_answer(self):
        r = self.anon.post(f"/api/questionnaire/{self.token}/submit/",
                           {"answers": {"soc2": {"answer": "yes"}}}, format="json")
        self.assertEqual(r.data["code"], "name")
        r = self.anon.post(f"/api/questionnaire/{self.token}/submit/",
                           {"answers": {}, "respondent_name": "Nia"}, format="json")
        self.assertEqual(r.data["code"], "answers")
        self.assertFalse(VendorAssessment.objects.exists())

    def test_an_expired_link_says_so_and_takes_nothing(self):
        QuestionnaireInvite.objects.filter(pk=self.invite.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=1))
        self.assertEqual(self.anon.get(f"/api/questionnaire/{self.token}/").data["status"], "expired")
        r = self.anon.post(f"/api/questionnaire/{self.token}/submit/",
                           {"answers": {"soc2": {"answer": "yes"}}, "respondent_name": "Nia"}, format="json")
        self.assertEqual(r.data["code"], "expired")

    def test_the_organisation_reviews_the_returned_answers(self):
        self.anon.post(f"/api/questionnaire/{self.token}/submit/",
                       {"answers": {"soc2": {"answer": "no"}}, "respondent_name": "Nia"}, format="json")
        a = VendorAssessment.objects.get()
        # The returned questionnaire surfaces to the owner and to managers,
        # until someone records an outcome.
        owner_keys = [i["key"] for i in build_feed(self.owner)]
        self.assertIn(f"vendor-questionnaire:{a.pk}", owner_keys)
        self.assertIn(f"vendor-questionnaire:{a.pk}", [i["key"] for i in build_feed(self.manager)])
        self.assertNotIn(f"vendor-questionnaire:{a.pk}", [i["key"] for i in build_feed(self.viewer)])
        r = self.client_for(self.manager).patch(f"/api/vendor-assessments/{a.pk}/",
                                                {"result": "exceptions"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["reviewed_by_name"], self.manager.get_full_name())
        self.assertNotIn(f"vendor-questionnaire:{a.pk}", [i["key"] for i in build_feed(self.owner)])
        # The vendor detail carries the invite history.
        detail = self.client_for(self.manager).get(f"/api/vendors/{self.vendor.pk}/").data
        self.assertEqual(detail["questionnaire_invites"][0]["status"], "submitted")
        self.assertEqual(detail["questionnaire_invites"][0]["assessment_result"], "exceptions")

    def test_a_lapsed_unanswered_link_is_flagged_to_the_owner(self):
        QuestionnaireInvite.objects.filter(pk=self.invite.pk).update(
            expires_at=timezone.now() - timezone.timedelta(days=2))
        keys = [i["key"] for i in build_feed(self.owner)]
        self.assertIn(f"vendor-questionnaire-lapsed:{self.invite.pk}", keys)

    def test_the_public_endpoints_are_throttled_on_their_own_scope(self):
        from unittest import mock
        from vendors.public_views import _QuestionnaireThrottle
        # DRF snapshots the rate table on the class at import; patch it there.
        with mock.patch.object(_QuestionnaireThrottle, "THROTTLE_RATES", {"questionnaire": "3/min"}):
            codes = [self.anon.get(f"/api/questionnaire/{self.token}/").status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_the_link_base_follows_the_request_when_public_url_is_unset(self):
        with override_settings(PUBLIC_URL=""):
            r = self.client_for(self.manager).post(
                f"/api/vendors/{self.vendor.pk}/questionnaire/send/", {}, format="json")
        self.assertTrue(re.match(r"^http://testserver/questionnaire/[A-Za-z0-9_-]{40,}$", r.data["link"]), r.data["link"])
