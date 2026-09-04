"""Folder RBAC, tree integrity, document lifecycle and upload validation."""
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from documents.models import EDIT, MANAGE, VIEW, Document, Folder, FolderPermission
from testutils import APITestBase, grant, make_doc
from audit.models import AuditLog
import socketserver
import struct
import threading
import time
from unittest import mock
from documents import clamav
from documents.scanning import eicar_bytes


class FolderVisibilityTests(APITestBase):
    def test_viewer_without_grants_sees_nothing(self):
        c = self.client_for(self.viewer)
        self.assertEqual(c.get("/api/folders/").data["count"], 0)
        self.assertEqual(c.get("/api/folders/tree/").data, [])
        self.assertEqual(c.get(f"/api/folders/{self.tree.root.pk}/").status_code, 404)

    def test_role_grant_is_inherited_and_mid_tree_folders_become_roots(self):
        grant(self.tree.cat, role=self.roles["Viewer"], level=VIEW)
        c = self.client_for(self.viewer)
        ids = {f["id"] for f in c.get("/api/folders/").data["results"]}
        self.assertEqual(ids, {self.tree.cat.pk, self.tree.ctrl1.pk, self.tree.ctrl2.pk})
        tree = c.get("/api/folders/tree/").data
        self.assertEqual([n["id"] for n in tree], [self.tree.cat.pk])
        self.assertEqual({n["id"] for n in tree[0]["children"]}, {self.tree.ctrl1.pk, self.tree.ctrl2.pk})
        self.assertEqual(tree[0]["my_access"], "view")

    def test_manager_and_superuser_see_everything(self):
        for u in (self.manager, self.admin):
            self.assertEqual(self.client_for(u).get("/api/folders/").data["count"], 4)

    def test_auditor_is_capped_at_view(self):
        grant(self.tree.root, role=self.roles["Auditor"], level=MANAGE)
        self.assertEqual(self.tree.ctrl1.effective_access(self.auditor), VIEW)
        c = self.client_for(self.auditor)
        r = c.post("/api/documents/", {
            "folder": self.tree.ctrl1.pk, "name": "x", "file": SimpleUploadedFile("x.txt", b"hi"),
        }, format="multipart")
        self.assertEqual(r.status_code, 403)

    def test_folder_permission_map_is_scoped_to_manageable_folders(self):
        grant(self.tree.cat, role=self.roles["Viewer"], level=VIEW)
        grant(self.tree.ctrl2, user=self.owner, level=MANAGE)
        self.assertEqual(self.client_for(self.viewer).get("/api/folder-permissions/").data["count"], 0)
        # owen manages ctrl2 only -> sees only grants on it
        self.assertEqual(
            {p["folder"] for p in self.client_for(self.owner).get("/api/folder-permissions/").data["results"]},
            {self.tree.ctrl2.pk},
        )
        self.assertEqual(self.client_for(self.manager).get("/api/folder-permissions/").data["count"], 2)

    def test_grant_requires_manage_on_that_folder(self):
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        c = self.client_for(self.owner)
        r = c.post("/api/folder-permissions/", {"folder": self.tree.ctrl1.pk, "role": self.roles["Viewer"].pk, "access_level": "view"}, format="json")
        self.assertEqual(r.status_code, 403)
        grant(self.tree.ctrl2, user=self.owner, level=MANAGE)
        r = c.post("/api/folder-permissions/", {"folder": self.tree.ctrl2.pk, "role": self.roles["Viewer"].pk, "access_level": "view"}, format="json")
        self.assertEqual(r.status_code, 201)
        # cannot repoint the grant to a folder they don't manage
        r = c.patch(f"/api/folder-permissions/{r.data['id']}/", {"folder": self.tree.ctrl1.pk}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_grant_needs_exactly_one_principal(self):
        c = self.client_for(self.manager)
        r = c.post("/api/folder-permissions/", {"folder": self.tree.ctrl1.pk, "access_level": "view"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = c.post("/api/folder-permissions/", {
            "folder": self.tree.ctrl1.pk, "access_level": "view",
            "role": self.roles["Viewer"].pk, "user": self.viewer.pk,
        }, format="json")
        self.assertEqual(r.status_code, 400)


class FolderIntegrityTests(APITestBase):
    def test_parent_cycle_is_rejected(self):
        c = self.client_for(self.manager)
        a = Folder.objects.create(name="A", parent=None)
        b = Folder.objects.create(name="B", parent=a)
        d = Folder.objects.create(name="D", parent=b)
        r = c.patch(f"/api/folders/{a.pk}/", {"parent": d.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        r = c.patch(f"/api/folders/{a.pk}/", {"parent": a.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        a.refresh_from_db()
        self.assertIsNone(a.parent)

    def test_corrupted_chain_raises_instead_of_hanging(self):
        a = Folder.objects.create(name="A")
        b = Folder.objects.create(name="B", parent=a)
        Folder.objects.filter(pk=a.pk).update(parent=b)  # bypass validation
        a.refresh_from_db()
        with self.assertRaises(ValidationError):
            a.ancestors()

    def test_folder_names_are_single_path_segments(self):
        c = self.client_for(self.manager)
        for bad in ("a/b", "a\\b", "..", ".", "trailing.", "nul\x00", "q?", "   "):
            r = c.post("/api/folders/", {"name": bad, "parent": self.tree.ctrl1.pk}, format="json")
            self.assertEqual(r.status_code, 400, bad)
        # surrounding whitespace is trimmed rather than rejected
        r = c.post("/api/folders/", {"name": "  2026 Q3 evidence ", "parent": self.tree.ctrl1.pk}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["name"], "2026 Q3 evidence")

    def test_seeded_folders_cannot_be_deleted_renamed_or_moved(self):
        c = self.client_for(self.admin)
        self.assertEqual(c.delete(f"/api/folders/{self.tree.root.pk}/").status_code, 403)
        self.assertEqual(c.delete(f"/api/folders/{self.tree.ctrl1.pk}/").status_code, 403)
        self.assertEqual(c.patch(f"/api/folders/{self.tree.ctrl1.pk}/", {"name": "renamed"}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"/api/folders/{self.tree.ctrl1.pk}/", {"parent": self.tree.root.pk}, format="json").status_code, 403)
        # but their owner and description-ish fields are editable
        self.assertEqual(c.patch(f"/api/folders/{self.tree.ctrl1.pk}/", {"owner": self.owner.pk}, format="json").status_code, 200)
        self.assertTrue(Folder.objects.filter(pk=self.tree.ctrl1.pk).exists())

    def test_user_folder_delete_and_move_rules(self):
        grant(self.tree.ctrl1, user=self.owner, level=MANAGE)
        grant(self.tree.ctrl2, user=self.owner, level=VIEW)
        c = self.client_for(self.owner)
        r = c.post("/api/folders/", {"name": "Scans", "parent": self.tree.ctrl1.pk}, format="json")
        self.assertEqual(r.status_code, 201)
        fid = r.data["id"]
        # moving under a folder with only view access is refused
        self.assertEqual(c.patch(f"/api/folders/{fid}/", {"parent": self.tree.ctrl2.pk}, format="json").status_code, 403)
        # making it top-level is reserved for folder managers
        self.assertEqual(c.patch(f"/api/folders/{fid}/", {"parent": None}, format="json").status_code, 403)
        # viewer without manage cannot delete it
        grant(self.tree.ctrl1, user=self.viewer, level=EDIT)
        self.assertEqual(self.client_for(self.viewer).delete(f"/api/folders/{fid}/").status_code, 403)
        self.assertEqual(c.delete(f"/api/folders/{fid}/").status_code, 204)


class DocumentLifecycleTests(APITestBase):
    def _upload(self, client, folder, name="Evidence", content=b"hello", filename="e.txt", **extra):
        payload = {"folder": folder.pk, "name": name, "file": SimpleUploadedFile(filename, content), **extra}
        return client.post("/api/documents/", payload, format="multipart")

    def test_upload_requires_edit_on_folder(self):
        grant(self.tree.ctrl1, role=self.roles["Control Owner"], level=VIEW)
        self.assertEqual(self._upload(self.client_for(self.owner), self.tree.ctrl1).status_code, 403)
        FolderPermission.objects.all().delete()
        grant(self.tree.ctrl1, role=self.roles["Control Owner"], level=EDIT)
        r = self._upload(self.client_for(self.owner), self.tree.ctrl1, review_cadence="quarterly")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["owner"], self.owner.pk)
        self.assertIsNotNone(r.data["next_review_date"])
        self.assertEqual(r.data["control_id"], None)  # control is set explicitly, not inferred

    def test_documents_are_hidden_outside_visible_folders(self):
        make_doc(self.tree.ctrl1, self.owner, name="Hidden")
        c = self.client_for(self.viewer)
        self.assertEqual(c.get("/api/documents/").data["count"], 0)
        self.assertEqual(c.get("/api/documents/reviews/").data, [])
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        self.assertEqual(c.get("/api/documents/").data["count"], 1)

    def test_owner_may_edit_but_not_delete_without_manage(self):
        grant(self.tree.ctrl1, role=self.roles["Control Owner"], level=VIEW)
        doc = make_doc(self.tree.ctrl1, self.owner)
        c = self.client_for(self.owner)
        r = c.patch(f"/api/documents/{doc.pk}/", {"description": "mine"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.delete(f"/api/documents/{doc.pk}/").status_code, 403)
        self.assertEqual(self.client_for(self.manager).delete(f"/api/documents/{doc.pk}/").status_code, 204)

    def test_move_requires_edit_on_destination(self):
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        grant(self.tree.ctrl2, user=self.owner, level=VIEW)
        doc = make_doc(self.tree.ctrl1, self.owner)
        c = self.client_for(self.owner)
        self.assertEqual(c.post(f"/api/documents/{doc.pk}/move/", {"folder": self.tree.ctrl2.pk}, format="json").status_code, 403)
        self.assertEqual(c.patch(f"/api/documents/{doc.pk}/", {"folder": self.tree.ctrl2.pk}, format="json").status_code, 403)
        self.assertEqual(c.post(f"/api/documents/{doc.pk}/move/", {"folder": 999999}, format="json").status_code, 400)

    def test_new_version_archives_previous_file(self):
        doc = make_doc(self.tree.ctrl1, self.owner)
        c = self.client_for(self.manager)
        r = c.post(f"/api/documents/{doc.pk}/new_version/", {"file": SimpleUploadedFile("v2.txt", b"v2"), "note": "rewrite"}, format="multipart")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["version"], 2)
        self.assertEqual(r.data["status"], "draft")
        versions = c.get(f"/api/documents/{doc.pk}/versions/").data
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["note"], "rewrite")
        self.assertEqual(c.post(f"/api/documents/{doc.pk}/new_version/", {}, format="multipart").status_code, 400)

    def test_mark_reviewed_resets_clock(self):
        doc = make_doc(self.tree.ctrl1, self.owner, cadence="quarterly", days=-5)
        doc.reminders_sent = [30, 14]
        doc.save()
        r = self.client_for(self.manager).post(f"/api/documents/{doc.pk}/mark_reviewed/")
        self.assertEqual(r.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.reminders_sent, [])
        self.assertEqual(doc.status, Document.Status.APPROVED)
        self.assertGreater(doc.days_until_review, 80)

    def test_reviews_horizon_is_clamped_and_sorted(self):
        make_doc(self.tree.ctrl1, self.owner, name="soon", days=3)
        make_doc(self.tree.ctrl1, self.owner, name="late", days=-2)
        make_doc(self.tree.ctrl1, self.owner, name="far", days=400)
        c = self.client_for(self.manager)
        names = [d["name"] for d in c.get("/api/documents/reviews/?days=abc").data]
        self.assertEqual(names, ["late", "soon"])
        names = [d["name"] for d in c.get("/api/documents/reviews/?days=99999").data]
        self.assertEqual(names, ["late", "soon", "far"])

    @override_settings(MAX_UPLOAD_BYTES=10, MAX_UPLOAD_MB=1)
    def test_upload_size_ceiling(self):
        c = self.client_for(self.manager)
        self.assertEqual(self._upload(c, self.tree.ctrl1, content=b"x" * 11).status_code, 400)
        self.assertEqual(self._upload(c, self.tree.ctrl1, content=b"x" * 10).status_code, 201)

    def test_active_content_extensions_are_refused(self):
        c = self.client_for(self.manager)
        for bad in ("evil.html", "evil.svg", "run.exe", "s.ps1"):
            self.assertEqual(self._upload(c, self.tree.ctrl1, filename=bad).status_code, 400, bad)
        self.assertEqual(self._upload(c, self.tree.ctrl1, content=b"", filename="empty.pdf").status_code, 400)
        self.assertEqual(self._upload(c, self.tree.ctrl1, filename="scan.pdf").status_code, 201)
        doc = Document.objects.get(name="Evidence")
        r = c.post(f"/api/documents/{doc.pk}/new_version/", {"file": SimpleUploadedFile("x.html", b"<x>")}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_unauthenticated_requests_are_rejected(self):
        self.assertEqual(self.client_for().get("/api/documents/").status_code, 401)
        self.assertEqual(self.client_for().get("/api/folders/tree/").status_code, 401)


class EvidenceDownloadTests(APITestBase):
    """Reading a stored file is an authorised, audited act.

    Before 0.3.0 nginx served the whole media volume as a plain alias, and
    upload paths are derived from the folder tree and the file name -- so
    anyone who could reach the site and guess a path could read any document,
    with nothing recorded.
    """

    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, name="Access Control Policy",
                            owner=self.owner, content=b"policy bytes")

    def test_a_user_with_folder_access_gets_the_bytes(self):
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        r = self.client_for(self.viewer).get(f"/api/documents/{self.doc.pk}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"policy bytes")

    def test_a_user_without_folder_access_gets_nothing(self):
        r = self.client_for(self.viewer).get(f"/api/documents/{self.doc.pk}/download/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/documents/{self.doc.pk}/download/").status_code, 401)

    def test_the_download_is_recorded_in_the_audit_trail(self):
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        before = AuditLog.objects.filter(action="read").count()
        self.client_for(self.viewer).get(f"/api/documents/{self.doc.pk}/download/")
        entry = AuditLog.objects.filter(action="read").latest("timestamp")
        self.assertEqual(AuditLog.objects.filter(action="read").count(), before + 1)
        self.assertEqual(entry.user, self.viewer)
        self.assertEqual(entry.object_type, "documents")
        self.assertIn("Access Control Policy", entry.detail)

    def test_the_response_is_always_an_attachment_and_never_inline(self):
        """An uploaded .html or .svg served inline would be stored XSS in the
        application's own origin."""
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        r = self.client_for(self.viewer).get(f"/api/documents/{self.doc.pk}/download/")
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.assertIn("no-store", r["Cache-Control"])

    def test_the_api_never_hands_out_a_storage_url(self):
        """The serializer must not publish a path that bypasses this view."""
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        r = self.client_for(self.viewer).get(f"/api/documents/{self.doc.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("/media/", str(r.data.get("file") or ""))

    @override_settings(MEDIA_INTERNAL=True, MEDIA_ACCEL_PREFIX="/protected-media/")
    def test_behind_an_accelerator_the_bytes_are_delegated_to_nginx(self):
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        r = self.client_for(self.viewer).get(f"/api/documents/{self.doc.pk}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["X-Accel-Redirect"].startswith("/protected-media/"))
        self.assertEqual(r.content, b"", "Django must not also send the body")
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))

    def test_an_archived_version_is_downloadable_under_the_same_rule(self):
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        c = self.client_for(self.owner)
        r = c.post(f"/api/documents/{self.doc.pk}/new_version/",
                   {"file": SimpleUploadedFile("v2.txt", b"second version")})
        self.assertEqual(r.status_code, 200, r.data)
        version_id = self.doc.versions.get().pk
        r = c.get(f"/api/documents/{self.doc.pk}/versions/{version_id}/download/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"policy bytes")
        # ...and someone with no access to the folder still gets nothing.
        self.assertEqual(
            self.client_for(self.viewer).get(
                f"/api/documents/{self.doc.pk}/versions/{version_id}/download/").status_code,
            404)


# --------------------------------------------------------------------------- #
# Malware scanning
# --------------------------------------------------------------------------- #
class FakeClamdHandler(socketserver.BaseRequestHandler):
    """Speaks just enough of the clamd protocol to exercise the client."""

    def handle(self):
        buf = b""
        while b"\0" not in buf:
            data = self.request.recv(64)
            if not data:
                return
            buf += data
        if buf.startswith(b"zPING\0"):
            self.request.sendall(b"PONG\0")
            return
        if not buf.startswith(b"zINSTREAM\0"):
            self.request.sendall(b"UNKNOWN COMMAND\0")
            return
        body = buf[len(b"zINSTREAM\0"):]
        received = b""
        while True:
            while len(body) < 4:
                data = self.request.recv(65536)
                if not data:
                    return
                body += data
            (n,) = struct.unpack("!L", body[:4])
            body = body[4:]
            if n == 0:
                break
            while len(body) < n:
                data = self.request.recv(65536)
                if not data:
                    return
                body += data
            received += body[:n]
            body = body[n:]
        self.server.received = received
        if self.server.hang:
            time.sleep(5)
        self.request.sendall(self.server.reply_for(received))


class FakeClamd(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FakeClamdHandler)
        self.received = b""
        self.hang = False
        self.forced = None

    def reply_for(self, payload):
        if self.forced:
            return self.forced
        if eicar_bytes() in payload:
            return b"stream: Win.Test.EICAR_HDB-1 FOUND\0"
        return b"stream: OK\0"


class VirusScanTests(APITestBase):
    """Scanning is off by default; when it is on it fails closed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clamd = FakeClamd()
        cls.clamd_thread = threading.Thread(target=cls.clamd.serve_forever, daemon=True)
        cls.clamd_thread.start()
        cls.clamd_host, cls.clamd_port = cls.clamd.server_address

    @classmethod
    def tearDownClass(cls):
        cls.clamd.shutdown()
        cls.clamd.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.clamd.received = b""
        self.clamd.hang = False
        self.clamd.forced = None
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)

    def scanning(self, **overrides):
        settings = dict(
            CLAMAV_ENABLED=True, CLAMAV_HOST=self.clamd_host, CLAMAV_PORT=self.clamd_port,
            CLAMAV_TIMEOUT=5, CLAMAV_CONNECT_TIMEOUT=2)
        settings.update(overrides)
        return override_settings(**settings)

    def upload(self, content, name="evidence.txt"):
        return self.client_for(self.owner).post("/api/documents/", {
            "name": "Scanned evidence", "folder": self.tree.ctrl1.pk,
            "file": SimpleUploadedFile(name, content),
        })

    # ---------------------------------------------------------------- default
    def test_scanning_is_off_by_default(self):
        """Benign bytes and a mock -- writing a real EICAR file into MEDIA_ROOT
        would be quarantined by on-access AV on a developer machine."""
        with mock.patch("documents.clamav.scan_stream") as scan:
            r = self.upload(b"an ordinary policy")
            self.assertEqual(r.status_code, 201, r.data)
            scan.assert_not_called()

    # ------------------------------------------------------------------- clean
    def test_a_clean_upload_is_stored_byte_for_byte(self):
        with self.scanning():
            r = self.upload(b"an ordinary policy")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.clamd.received, b"an ordinary policy")
        doc = Document.objects.get(pk=r.data["id"])
        with doc.file.open("rb") as fh:
            self.assertEqual(fh.read(), b"an ordinary policy",
                             "the scan must not consume the upload")

    # ---------------------------------------------------------------- infected
    def test_an_infected_upload_is_refused_audited_and_not_stored(self):
        before = Document.objects.count()
        with self.scanning():
            r = self.upload(eicar_bytes())
        self.assertEqual(r.status_code, 400)
        self.assertIn("Win.Test.EICAR_HDB-1", str(r.data))
        self.assertEqual(Document.objects.count(), before, "nothing may be stored")
        entry = AuditLog.objects.filter(detail__contains="refused infected upload").latest("timestamp")
        self.assertEqual(entry.user, self.owner)
        self.assertIn("Win.Test.EICAR_HDB-1", entry.detail)

    def test_the_detection_row_survives_the_drf_exception_handler(self):
        with self.scanning():
            self.upload(eicar_bytes())
        self.assertTrue(
            AuditLog.objects.filter(detail__contains="refused infected upload").exists(),
            "DRF's handler calls set_rollback(); the row must still be there")

    # ------------------------------------------------------------ authorization
    def test_scanning_runs_after_the_folder_permission_check(self):
        """A caller who may not write to the folder must never reach the
        scanner: that would be a signature-set oracle and a DoS lever."""
        with self.scanning():
            r = self.client_for(self.viewer).post("/api/documents/", {
                "name": "Not allowed", "folder": self.tree.ctrl1.pk,
                "file": SimpleUploadedFile("x.txt", eicar_bytes()),
            })
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.clamd.received, b"", "the scanner must not have been called")

    # ------------------------------------------------------------- fail closed
    def test_an_unreachable_scanner_fails_closed(self):
        before = Document.objects.count()
        with override_settings(CLAMAV_ENABLED=True, CLAMAV_HOST="127.0.0.1",
                               CLAMAV_PORT=1, CLAMAV_CONNECT_TIMEOUT=1):
            r = self.upload(b"harmless")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(Document.objects.count(), before)

    def test_a_hanging_scanner_fails_closed(self):
        self.clamd.hang = True
        with self.scanning(CLAMAV_TIMEOUT=1):
            r = self.upload(b"harmless")
        self.assertEqual(r.status_code, 503)

    # --------------------------------------------------------- limits exceeded
    def test_content_the_scanner_could_not_inspect_is_refused_not_called_malware(self):
        """ClamAV reports Heuristics.Limits.Exceeded as FOUND. Storing it would
        mean keeping a file that carries the claim it was scanned; calling it
        malware would be a lie in the other direction."""
        self.clamd.forced = b"stream: Heuristics.Limits.Exceeded.MaxFileSize FOUND\0"
        with self.scanning():
            r = self.upload(b"a big archive")
        self.assertEqual(r.status_code, 400)
        self.assertIn("could not be fully inspected", str(r.data))
        self.assertFalse(
            AuditLog.objects.filter(detail__contains="refused infected upload").exists(),
            "this is not a detection")

    def test_a_file_over_the_stream_limit_is_refused_before_it_is_sent(self):
        with self.scanning(CLAMAV_MAX_BYTES=8):
            r = self.upload(b"considerably longer than eight bytes")
        self.assertEqual(r.status_code, 400)
        self.assertIn("could not be fully inspected", str(r.data))

    # -------------------------------------------------------------- every path
    def test_a_new_version_is_scanned(self):
        doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Versioned")
        with self.scanning():
            r = self.client_for(self.owner).post(
                f"/api/documents/{doc.pk}/new_version/",
                {"file": SimpleUploadedFile("v2.txt", eicar_bytes())})
        self.assertEqual(r.status_code, 400)
        doc.refresh_from_db()
        self.assertEqual(doc.version, 1, "the version must not have been bumped")

    def test_meeting_minutes_are_scanned(self):
        from governance.models import MeetingSeries

        series = MeetingSeries.objects.create(name="Steering", required_per_year=4)
        with self.scanning():
            r = self.client_for(self.manager).post("/api/meeting-minutes/", {
                "series": series.pk, "date": "2026-01-15", "title": "Q1",
                "file": SimpleUploadedFile("m.txt", eicar_bytes()),
            })
        self.assertEqual(r.status_code, 400)

    def test_form_templates_are_scanned(self):
        with self.scanning():
            r = self.client_for(self.manager).post("/api/form-templates/", {
                "name": "Blank form", "category": "policy",
                "file": SimpleUploadedFile("t.txt", eicar_bytes()),
            })
        self.assertEqual(r.status_code, 400)

    # ---------------------------------------------------------------- protocol
    def test_the_protocol_vectors(self):
        self.assertIsNone(clamav.parse_response("stream: OK"))
        with self.assertRaises(clamav.InfectedError) as cm:
            clamav.parse_response("stream: Eicar-Signature FOUND")
        self.assertEqual(cm.exception.signature, "Eicar-Signature")
        with self.assertRaises(clamav.LimitsExceededError):
            clamav.parse_response("stream: Heuristics.Limits.Exceeded.MaxRecursion FOUND")
        for bad in ("stream: whatever ERROR", "", "nonsense"):
            with self.assertRaises(clamav.ScanError):
                clamav.parse_response(bad)

    def test_the_boot_probe_answers(self):
        self.assertTrue(clamav.ping(self.clamd_host, self.clamd_port, timeout=2))
        self.assertFalse(clamav.ping("127.0.0.1", 1, timeout=1))

    def test_the_eicar_fixture_is_the_standard_file(self):
        self.assertEqual(len(eicar_bytes()), 68)
        self.assertTrue(eicar_bytes().startswith(b"X5O!P%@AP[4"))
