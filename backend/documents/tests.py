"""Folder RBAC, tree integrity, document lifecycle and upload validation."""
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from documents.models import EDIT, MANAGE, VIEW, Document, Folder, FolderPermission
from testutils import APITestBase, grant, make_doc


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
