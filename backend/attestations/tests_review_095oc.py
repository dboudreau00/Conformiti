from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from attestations.models import PackageControl, PackageEvidence, PbcItem, PbcRequest
from attestations.tests_pbc import PbcBase
from documents.models import DocumentVersion
from governance.models import Risk
from notifications.tasks import OVERDUE, run_pbc_scan


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local",
                   REVIEW_ALERT_LEAD_DAYS=[30, 14, 7, 1])
class PbcScanRaceTests(PbcBase):
    @staticmethod
    def _race(action):
        """Run ``action`` once, between the scan reading the lines and its conditional claim."""
        real_filter = PbcRequest.objects.filter
        raced = []

        def filter_(*args, **kwargs):
            if "reminders_sent" in kwargs and not raced:
                raced.append(True)
                action()
            return real_filter(*args, **kwargs)

        return mock.patch.object(PbcRequest.objects, "filter", side_effect=filter_)

    def _overdue_line(self):
        return self.raise_line(
            self.manager_client, title="Late", assignee=self.owner.pk,
            due_date=str(timezone.localdate() - timezone.timedelta(days=1))).data

    def test_a_line_answered_during_the_scan_is_not_chased(self):
        line = self._overdue_line()

        def answered():
            response = self.manager_client.post(
                f"/api/pbc-requests/{line['id']}/provide/", {"response_note": "done"}, format="json")
            self.assertEqual(response.status_code, 200, response.data)

        with self._race(answered):
            run_pbc_scan()
        self.assertEqual(PbcRequest.objects.get(pk=line["id"]).reminders_sent, [])
        self.assertEqual(len(mail.outbox), 0, "an overdue notice for a line that was just answered")

    def test_a_line_given_a_new_date_during_the_scan_is_not_stamped_for_the_old_one(self):
        line = self._overdue_line()
        later = str(timezone.localdate() + timezone.timedelta(days=60))

        def postponed():
            response = self.manager_client.patch(
                f"/api/pbc-requests/{line['id']}/", {"due_date": later}, format="json")
            self.assertEqual(response.status_code, 200, response.data)

        with self._race(postponed):
            run_pbc_scan()
        self.assertEqual(PbcRequest.objects.get(pk=line["id"]).reminders_sent, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_an_undisturbed_scan_still_chases_the_line(self):
        line = self._overdue_line()
        run_pbc_scan()
        self.assertEqual(PbcRequest.objects.get(pk=line["id"]).reminders_sent, [OVERDUE])
        self.assertEqual(len(mail.outbox), 1)


class WithdrawnPackageTests(PbcBase):
    """A sealed package still takes the management response and a finding raised as a risk; a withdrawn one takes
    nothing."""

    def _withdraw(self):
        response = self.manager_client.post(
            f"/api/evidence-packages/{self.package.pk}/withdraw/", {"reason": "Fieldwork complete"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_the_management_response_is_written_while_sealed_and_frozen_once_withdrawn(self):
        row = PackageControl.objects.get(package=self.package)
        written = self.manager_client.patch(
            f"/api/package-controls/{row.pk}/", {"management_response": "Agreed."}, format="json")
        self.assertEqual(written.status_code, 200, written.data)
        self._withdraw()
        frozen = self.manager_client.patch(
            f"/api/package-controls/{row.pk}/", {"management_response": "Rewritten after withdrawal"}, format="json")
        self.assertEqual(frozen.status_code, 400, frozen.data)
        row.refresh_from_db()
        self.assertEqual(row.management_response, "Agreed.")

    def test_a_finding_becomes_a_risk_while_sealed(self):
        row = PackageControl.objects.get(package=self.package)
        PackageControl.objects.filter(pk=row.pk).update(operating_conclusion=PackageControl.Conclusion.EXCEPTIONS)
        raised = self.manager_client.post(f"/api/package-controls/{row.pk}/promote/")
        self.assertEqual(raised.status_code, 201, raised.data)
        self.assertEqual(Risk.objects.filter(risk_type=Risk.Type.AUDIT_FINDING).count(), 1)

    def test_a_finding_does_not_become_a_risk_once_withdrawn(self):
        row = PackageControl.objects.get(package=self.package)
        PackageControl.objects.filter(pk=row.pk).update(operating_conclusion=PackageControl.Conclusion.EXCEPTIONS)
        self._withdraw()
        refused = self.manager_client.post(f"/api/package-controls/{row.pk}/promote/")
        self.assertEqual(refused.status_code, 400, refused.data)
        self.assertFalse(Risk.objects.filter(risk_type=Risk.Type.AUDIT_FINDING).exists())
        row.refresh_from_db()
        self.assertIsNone(row.risk_id)

    def test_the_request_list_takes_no_answer_judgement_withdrawal_or_detachment_once_withdrawn(self):
        waiting = self.raise_line(self.manager_client, title="Waiting", assignee=self.owner.pk).data
        provided = self.raise_line(self.manager_client, title="Provided").data
        sent = self.manager_client.post(
            f"/api/pbc-requests/{provided['id']}/provide/", {"response_note": "sent"}, format="json")
        self.assertEqual(sent.status_code, 200, sent.data)
        attached = self.raise_line(self.manager_client, title="Attached").data
        item = self.manager_client.post(
            "/api/pbc-items/", {"request": attached["id"], "document": self.doc.pk}, format="json")
        self.assertEqual(item.status_code, 201, item.data)
        self.assertEqual(self.manager_client.post(
            f"/api/pbc-requests/{attached['id']}/provide/", {}, format="json").status_code, 200)
        self._withdraw()

        for label, path, body in (
            ("provide", f"/api/pbc-requests/{waiting['id']}/provide/", {"response_note": "late"}),
            ("accept", f"/api/pbc-requests/{provided['id']}/accept/", {}),
            ("return", f"/api/pbc-requests/{provided['id']}/return/", {"returned_note": "no"}),
            ("withdraw", f"/api/pbc-requests/{waiting['id']}/withdraw/", {}),
        ):
            with self.subTest(label):
                response = self.manager_client.post(path, body, format="json")
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("closed", str(response.data))
        detach = self.manager_client.delete(f"/api/pbc-items/{item.data['id']}/")
        self.assertEqual(detach.status_code, 400, getattr(detach, "data", None))

        self.assertEqual(PbcRequest.objects.get(pk=waiting["id"]).status, PbcRequest.Status.OPEN)
        self.assertEqual(PbcRequest.objects.get(pk=provided["id"]).status, PbcRequest.Status.PROVIDED)
        self.assertEqual(PbcRequest.objects.get(pk=attached["id"]).status, PbcRequest.Status.PROVIDED)
        self.assertEqual(PbcRequest.objects.get(pk=attached["id"]).items.count(), 1)


class QuarantinedArchiveTests(PbcBase):
    """FIL-03: an archived version the sweep quarantined is refused wherever a package or a request line still serves
    it, although the document's current file is clean."""

    def setUp(self):
        super().setUp()
        self.item = PackageEvidence.objects.get()
        line = self.raise_line(self.manager_client).data
        attached = self.manager_client.post("/api/pbc-items/", {"request": line["id"], "document": self.doc.pk},
                                            format="json")
        self.assertEqual(attached.status_code, 201, attached.data)
        self.pbc_item = PbcItem.objects.get()
        r = self.manager_client.post(f"/api/documents/{self.doc.pk}/new_version/",
                                     {"file": SimpleUploadedFile("policy-v2.txt", b"rewritten")}, format="multipart")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))
        DocumentVersion.objects.filter(document=self.doc, version=1).update(
            quarantined_at=timezone.now(), scan_status="infected", scan_signature="Test.Marker")

    def assert_refused(self, response):
        self.assertEqual(response.status_code, 403, getattr(response, "data", response))
        self.assertIn("quarantined", str(response.data["detail"]))

    def test_the_pinned_evidence_file_and_its_preview_are_refused(self):
        for route in ("file", "preview"):
            with self.subTest(route):
                self.assert_refused(self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/{route}/"))

    def test_the_export_is_refused(self):
        self.assert_refused(self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/export/"))

    def test_the_request_line_attachment_is_refused(self):
        for route in ("file", "preview"):
            with self.subTest(route):
                self.assert_refused(self.auditor_client.get(f"/api/pbc-items/{self.pbc_item.pk}/{route}/"))

    def test_the_current_file_still_reaches_its_readers(self):
        self.assertEqual(self.manager_client.get(f"/api/documents/{self.doc.pk}/download/").status_code, 200)
