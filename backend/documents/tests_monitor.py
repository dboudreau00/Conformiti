"""Scanner monitoring: the probe, the re-scan sweep, quarantine on every byte
route, the health endpoint, the tray, and the outage email."""
import threading
from io import StringIO

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from rest_framework.test import APIClient

from attestations.tests import PackageTestBase
from audit.models import AuditLog
from documents import monitor
from documents.models import Document, ScannerStatus
from documents.scanning import eicar_bytes
from documents.tests import FakeClamd
from notifications.notifications import build as build_feed
from notifications.tasks import run_scanner_watch
from testutils import APITestBase, grant, make_doc, VIEW


class ClamdMixin:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clamd = FakeClamd()
        cls.thread = threading.Thread(target=cls.clamd.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.clamd.server_address

    @classmethod
    def tearDownClass(cls):
        cls.clamd.shutdown()
        cls.clamd.server_close()
        super().tearDownClass()

    def scanning(self, **overrides):
        s = dict(CLAMAV_ENABLED=True, CLAMAV_HOST=self.host, CLAMAV_PORT=self.port,
                 CLAMAV_TIMEOUT=5, CLAMAV_CONNECT_TIMEOUT=2)
        s.update(overrides)
        return override_settings(**s)


@override_settings(EMAIL_PROVIDER="console", COMPLIANCE_TEAM_EMAIL="grc@test.local")
class MonitorTests(ClamdMixin, APITestBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.clamd.forced = None
        grant(self.tree.ctrl1, user=self.owner, level=VIEW)

    def test_the_probe_is_off_by_default_and_cached_when_on(self):
        self.assertEqual(monitor.probe()["enabled"], False)
        with self.scanning():
            first = monitor.probe()
            self.assertTrue(first["reachable"])
            self.assertIsNotNone(first["latency_ms"])
            with self.scanning(CLAMAV_PORT=1):        # nothing listens here
                self.assertTrue(monitor.probe()["reachable"])   # cached
                self.assertFalse(monitor.probe(force=True)["reachable"])
                self.assertIsNotNone(ScannerStatus.load().down_since)

    def test_health_reports_the_scanner(self):
        anon = APIClient()
        self.assertEqual(anon.get("/api/health/").data["scanning"]["enabled"], False)
        with self.scanning():
            body = anon.get("/api/health/").data["scanning"]
            self.assertEqual((body["enabled"], body["reachable"]), (True, True))

    def test_a_rescan_quarantines_an_infected_file_on_every_route(self):
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Innocent then not", content=b"benign")
        with self.scanning():
            self.assertEqual(monitor.scan_document(doc), "clean")
            doc.refresh_from_db()
            self.assertIsNotNone(doc.scanned_at)
            # New definitions: the same bytes now match.
            self.clamd.forced = b"stream: Win.Test.EICAR_HDB-1 FOUND\0"
            self.assertEqual(monitor.scan_document(doc), "infected")
            doc.refresh_from_db()
            self.assertTrue(doc.is_quarantined)
            self.assertEqual(doc.scan_signature, "Win.Test.EICAR_HDB-1")
            self.assertTrue(AuditLog.objects.filter(detail__startswith="QUARANTINED").exists())
        # Quarantine is enforced whether or not scanning is still on.
        c = self.client_for(self.owner)
        r = c.get(f"/api/documents/{doc.pk}/download/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("quarantined", str(r.data["detail"]))
        self.assertEqual(c.get(f"/api/documents/{doc.pk}/preview/").status_code, 403)
        listed = c.get(f"/api/documents/{doc.pk}/").data
        self.assertEqual((listed["quarantined"], listed["scan_status"]), (True, "infected"))
        # Managers and admins are told in the tray.
        self.assertIn("digest-quarantined", [i["key"] for i in build_feed(self.manager)])
        self.assertNotIn("digest-quarantined", [i["key"] for i in build_feed(self.viewer)])
        # A later clean re-scan releases it, and that is recorded too.
        with self.scanning():
            self.clamd.forced = None
            self.assertEqual(monitor.scan_document(doc), "clean")
        doc.refresh_from_db()
        self.assertFalse(doc.is_quarantined)
        self.assertTrue(AuditLog.objects.filter(detail__startswith="released").exists())
        self.assertEqual(c.get(f"/api/documents/{doc.pk}/download/").status_code, 200)

    def test_an_unreachable_scanner_is_recorded_as_error_not_clean(self):
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Unscannable", content=b"x")
        with self.scanning(CLAMAV_PORT=1):
            self.assertEqual(monitor.scan_document(doc), "error")
        doc.refresh_from_db()
        self.assertFalse(doc.is_quarantined)
        # Refused or timed out, depending on the platform; recorded either way.
        self.assertTrue(doc.scan_signature)
        self.assertEqual(doc.scan_status, "error")

    def test_uploads_are_marked_clean_and_a_new_version_resets_the_verdict(self):
        grant(self.tree.ctrl1, user=self.owner, level="edit")
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = self.client_for(self.owner)
        with self.scanning():
            r = c.post("/api/documents/", {"name": "Fresh", "folder": self.tree.ctrl1.pk,
                                           "file": SimpleUploadedFile("fresh.txt", b"fresh")})
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(r.data["scan_status"], "clean")
            doc = Document.objects.get(pk=r.data["id"])
            Document.objects.filter(pk=doc.pk).update(quarantined_at=doc.created_at, scan_status="infected")
            r = c.post(f"/api/documents/{doc.pk}/new_version/",
                       {"file": SimpleUploadedFile("fresh2.txt", b"fresh2")})
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual((r.data["quarantined"], r.data["scan_status"]), (False, "clean"))

    def test_the_command_sweeps_probes_and_exits_nonzero_on_infection(self):
        out = StringIO()
        call_command("scan_evidence", stdout=out)
        self.assertIn("OFF", out.getvalue())
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Sweep me", content=b"z")
        with self.scanning():
            out = StringIO()
            call_command("scan_evidence", "--probe", stdout=out)
            self.assertIn("answered", out.getvalue())
            out = StringIO()
            call_command("scan_evidence", "--all", "--dry-run", stdout=out)
            self.assertIn("would be scanned: 1", out.getvalue())
            doc.refresh_from_db()
            self.assertIsNone(doc.scanned_at)
            call_command("scan_evidence", "--all", stdout=StringIO())
            doc.refresh_from_db()
            self.assertEqual(doc.scan_status, "clean")
            # Recently scanned files are skipped by the stale window.
            out = StringIO()
            call_command("scan_evidence", "--stale", "30", "--dry-run", stdout=out)
            self.assertIn("would be scanned: 0", out.getvalue())
            self.clamd.forced = b"stream: Eicar-Test-Signature FOUND\0"
            with self.assertRaises(CommandError):
                call_command("scan_evidence", "--all", stdout=StringIO())
        with self.scanning(CLAMAV_PORT=1):
            with self.assertRaises(CommandError):
                call_command("scan_evidence", "--probe", stdout=StringIO())

    def test_the_watch_emails_once_per_outage_and_once_on_recovery(self):
        self.assertEqual(run_scanner_watch(), "off")
        with self.scanning(CLAMAV_PORT=1):
            self.assertEqual(run_scanner_watch(), "down")
            self.assertEqual(run_scanner_watch(), "down")
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("[Alert]", mail.outbox[0].subject)
            self.assertEqual(mail.outbox[0].to, ["grc@test.local"])
            self.assertIn("scanner-down", [i["key"] for i in build_feed(self.admin)])
        with self.scanning():
            self.assertEqual(run_scanner_watch(), "recovered")
            self.assertEqual(run_scanner_watch(), "up")
            self.assertEqual(len(mail.outbox), 2)
            self.assertIn("[Recovered]", mail.outbox[1].subject)
            self.assertNotIn("scanner-down", [i["key"] for i in build_feed(self.admin)])
            # A second outage is a second alert.
            with self.scanning(CLAMAV_PORT=1):
                self.assertEqual(run_scanner_watch(), "down")
            self.assertEqual(len(mail.outbox), 3)

    def test_a_sweep_counts_what_the_scanner_flags(self):
        # Benign bytes and a forced verdict: writing a real EICAR file into
        # MEDIA_ROOT gets it eaten by on-access antivirus on a developer box,
        # and the sweep would then count an unreadable file, not an infection.
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Test file", content=b"plain")
        with self.scanning():
            self.clamd.forced = b"stream: Win.Test.EICAR_HDB-1 FOUND\0"
            self.assertEqual(monitor.rescan(Document.objects.filter(pk=doc.pk))["infected"], 1)
        self.assertTrue(Document.objects.get(pk=doc.pk).is_quarantined)
        self.assertEqual(len(eicar_bytes()), 68)


class PackageQuarantineTests(ClamdMixin, PackageTestBase):
    def test_pinned_evidence_and_pbc_items_refuse_quarantined_bytes(self):
        self.add_control()
        self.seal()
        self.issue_to(self.auditor)
        Document.objects.filter(pk=self.doc.pk).update(
            quarantined_at=self.doc.created_at, scan_status="infected", scan_signature="Test.Sig")
        item = self.package.controls.get().evidence.get()
        c = self.client_for(self.auditor)
        self.assertEqual(c.get(f"/api/package-evidence/{item.pk}/file/").status_code, 403)
        self.assertEqual(c.get(f"/api/package-evidence/{item.pk}/preview/").status_code, 403)
        # The export still runs; the manifest is a record, not a delivery of the bytes.
        line = self.manager_client.post("/api/pbc-requests/", {"package": self.package.pk, "title": "x"},
                                        format="json").data
        pbc = self.manager_client.post("/api/pbc-items/", {"request": line["id"], "document": self.doc.pk},
                                       format="json").data
        self.assertEqual(c.get(f"/api/pbc-items/{pbc['id']}/file/").status_code, 403)
