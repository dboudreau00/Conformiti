from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from notifications.tasks import run_vendor_scan
from testutils import APITestBase
from vendors import assurance
from vendors.models import SharedResponsibility, Vendor, VendorAssessment


class MatrixControlIdTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.vendor = Vendor.objects.create(name="Northwind Cloud", category="Cloud hosting", tier="critical")
        self.url = f"/api/vendors/{self.vendor.pk}/matrix/"
        self.client = self.client_for(self.manager)

    def _save(self, control):
        return self.client.put(self.url, {"rows": [
            {"control": control, "responsibility": "provider", "provider_statement": "We run it."}]}, format="json")

    def test_true_and_a_fraction_do_not_name_a_control(self):
        # True is 1 and 1.9 truncates to 1: both used to land on the control whose id is 1.
        for bad in (True, False, self.tree.c1.pk + 0.9, float(self.tree.c1.pk)):
            with self.subTest(control=bad):
                response = self._save(bad)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(SharedResponsibility.objects.filter(vendor=self.vendor).exists())

    def test_a_whole_number_or_its_digits_still_do(self):
        for good in (self.tree.c1.pk, str(self.tree.c1.pk)):
            with self.subTest(control=good):
                response = self._save(good)
                self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(SharedResponsibility.objects.filter(vendor=self.vendor).count(), 1)

    def test_text_that_is_not_a_number_is_refused(self):
        self.assertEqual(self._save("12.5").status_code, 400)
        self.assertEqual(self._save("first").status_code, 400)


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local")
class BridgeLetterScanRaceTests(APITestBase):
    def test_a_bridge_letter_filed_after_the_gaps_were_listed_closes_the_gap(self):
        vendor = Vendor.objects.create(name="Northwind Cloud", category="Cloud hosting", tier="critical",
                                       owner=self.owner)
        report = VendorAssessment.objects.create(
            vendor=vendor, kind="soc2_type2", result="satisfactory",
            expires_at=timezone.localdate() - timedelta(days=3))
        real_gaps = assurance.bridge_letter_gaps

        def gaps_then_a_letter(*args, **kwargs):
            listed = real_gaps(*args, **kwargs)
            VendorAssessment.objects.create(
                vendor=vendor, kind="bridge_letter", result="satisfactory",
                expires_at=timezone.localdate() + timedelta(days=60))
            return listed

        with mock.patch.object(assurance, "bridge_letter_gaps", gaps_then_a_letter):
            self.assertEqual(run_vendor_scan(), 0)
        report.refresh_from_db()
        self.assertIsNone(report.bridge_reminded_at)
        self.assertEqual(len(mail.outbox), 0, "a bridge letter was asked for after one was filed")

    def test_an_open_gap_is_still_chased(self):
        vendor = Vendor.objects.create(name="Northwind Cloud", category="Cloud hosting", tier="critical",
                                       owner=self.owner)
        VendorAssessment.objects.create(
            vendor=vendor, kind="soc2_type2", result="satisfactory",
            expires_at=timezone.localdate() - timedelta(days=3))
        self.assertEqual(run_vendor_scan(), 1)
        self.assertEqual(len(mail.outbox), 1)


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local", PUBLIC_URL="https://grc.example")
class QuestionnaireDraftAuditTests(APITestBase):
    """FIL-06: an anonymous respondent saving a draft leaves an audit row that never holds the answers."""

    def test_saving_a_draft_writes_an_audit_row_without_the_answers(self):
        from audit.models import AuditLog
        from rest_framework.test import APIClient

        vendor = Vendor.objects.create(name="Northwind Cloud", contact_email="sec@northwind.example")
        sent = self.client_for(self.manager).post(f"/api/vendors/{vendor.pk}/questionnaire/send/", {}, format="json")
        token = sent.data["link"].rsplit("/", 1)[1]
        before = AuditLog.objects.filter(object_type="vendor-questionnaire", action="update").count()
        r = APIClient().put(f"/api/questionnaire/{token}/", {"answers": {
            "soc2": {"answer": "no", "note": "We do not encrypt backups"}}}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rows = AuditLog.objects.filter(object_type="vendor-questionnaire", action="update")
        self.assertEqual(rows.count(), before + 1)
        row = rows.latest("pk")
        self.assertIsNone(row.user)
        self.assertIn("Northwind Cloud", row.detail)
        self.assertNotIn("encrypt", row.detail)


class HiddenReportIdTests(APITestBase):
    """FIL-07: a hidden document id and a missing one get the same error text."""

    def test_hidden_and_missing_document_ids_are_answered_alike(self):
        from documents.models import Document
        from testutils import make_doc

        vendor = Vendor.objects.create(name="Northwind Cloud")
        hidden = make_doc(self.tree.ctrl2, owner=self.owner, name="SOC report")
        role = self.roles["Compliance Manager"]
        role.can_view_all = False
        role.can_manage_folders = False
        role.save()
        missing = Document.objects.order_by("-pk").first().pk + 1000
        client = self.client_for(self.manager)
        answers = []
        for pk in (hidden.pk, missing):
            r = client.post("/api/vendor-assessments/", {"vendor": vendor.pk, "kind": "soc2_type2", "document": pk},
                            format="json")
            self.assertEqual(r.status_code, 400, r.data)
            answers.append((str(r.data["document"][0]).replace(str(pk), "N"), r.data["document"][0].code))
        self.assertEqual(answers[0], answers[1])
        self.assertNotIn("cannot see", answers[0][0])


class VendorCadenceCalendarTests(APITestBase):
    """ROB-10: annual and biennial land on the calendar anniversary across 29 February."""

    def test_annual_and_biennial_keep_the_anniversary(self):
        from datetime import date

        for cadence, expected in (("annual", date(2025, 1, 15)), ("biennial", date(2026, 1, 15)),
                                  ("quarterly", date(2024, 1, 15) + timedelta(days=91)),
                                  ("semiannual", date(2024, 1, 15) + timedelta(days=182))):
            with self.subTest(cadence=cadence):
                vendor = Vendor(name=f"V {cadence}", review_cadence=cadence, last_reviewed=date(2024, 1, 15))
                self.assertEqual(vendor.compute_next_review(), expected)


@override_settings(TIME_ZONE="Pacific/Auckland")
class VendorLocalDayTests(APITestBase):
    """ROB-04: a vendor created late in the UTC day is onboarded on the local calendar day."""

    def test_the_cadence_counts_from_the_local_day_of_creation(self):
        from datetime import date, datetime, timezone as dt_tz

        vendor = Vendor.objects.create(name="Northwind Cloud", review_cadence="quarterly")
        # 20:00 UTC on 4 November is 09:00 on 5 November in Auckland.
        Vendor.objects.filter(pk=vendor.pk).update(created_at=datetime(2026, 11, 4, 20, 0, tzinfo=dt_tz.utc))
        vendor.refresh_from_db()
        self.assertEqual(vendor.compute_next_review(), date(2026, 11, 5) + timedelta(days=91))
