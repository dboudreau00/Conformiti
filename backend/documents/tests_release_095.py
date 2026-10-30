from django.utils import timezone

from documents.models import EDIT, MANAGE, VIEW, Document, Folder
from notifications.tasks import OVERDUE, run_review_scan
from testutils import APITestBase, assert_same_as_missing, grant, make_doc


class ReviewClockTests(APITestBase):
    def setUp(self):
        super().setUp()
        # last_reviewed makes the stored next_review_date what the cadence computes, so an edit that does not touch
        # the clock recomputes the same date.
        self.doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Policy", days=-3)
        self.doc.last_reviewed = timezone.localdate() - timezone.timedelta(days=395)
        self.doc.compute_next_review()
        self.doc.save()
        self.assertLess(self.doc.next_review_date, timezone.localdate())

    def test_editing_the_review_date_clears_the_reminders_sent(self):
        self.assertEqual(run_review_scan(), 1)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.reminders_sent, [OVERDUE])
        self.assertEqual(self.doc.status, Document.Status.EXPIRED)

        r = self.client_for(self.manager).patch(
            f"/api/documents/{self.doc.pk}/",
            {"last_reviewed": timezone.localdate().isoformat()}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.doc.refresh_from_db()
        self.assertGreater(self.doc.next_review_date, timezone.localdate())
        self.assertEqual(self.doc.reminders_sent, [])

        Document.objects.filter(pk=self.doc.pk).update(
            next_review_date=timezone.localdate() - timezone.timedelta(days=1))
        self.assertEqual(run_review_scan(), 1)

    def test_a_patch_that_leaves_the_date_alone_keeps_the_record(self):
        run_review_scan()
        r = self.client_for(self.manager).patch(
            f"/api/documents/{self.doc.pk}/", {"description": "renamed"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.reminders_sent, [OVERDUE],
                         "an unrelated edit must not re-send the overdue notice")


class FolderTreeQueryTests(APITestBase):
    def setUp(self):
        super().setUp()
        grant(self.tree.cat, role=self.roles["Viewer"], level=VIEW)
        grant(self.tree.ctrl2, user=self.viewer, level=EDIT)
        for i in range(30):
            sub = Folder.objects.create(name=f"Sub {i:02d}", parent=self.tree.ctrl1)
            make_doc(sub, owner=self.owner, name=f"Doc {i}")

    def count_queries(self, client):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            r = client.get("/api/folders/tree/")
        self.assertEqual(r.status_code, 200)
        return len(ctx.captured_queries), r.data

    def test_the_query_count_does_not_grow_with_the_number_of_folders(self):
        client = self.client_for(self.viewer)
        thirty, data = self.count_queries(client)
        for i in range(30, 60):
            sub = Folder.objects.create(name=f"Sub {i:02d}", parent=self.tree.ctrl1)
            make_doc(sub, owner=self.owner, name=f"Doc {i}")
        sixty, _ = self.count_queries(client)
        self.assertEqual(sixty, thirty,
                         f"{thirty} queries for 34 folders, {sixty} for 64: the tree is "
                         "querying per node again")
        self.assertLess(thirty, 20)

        cat = data[0]
        self.assertEqual(cat["my_access"], "view")
        ctrl2 = next(n for n in cat["children"] if n["id"] == self.tree.ctrl2.pk)
        self.assertEqual(ctrl2["my_access"], "edit", "a direct grant still beats the inherited one")
        ctrl1 = next(n for n in cat["children"] if n["id"] == self.tree.ctrl1.pk)
        self.assertEqual(len(ctrl1["children"]), 30)
        self.assertTrue(all(n["document_count"] == 1 for n in ctrl1["children"]))

    def test_the_bulk_answer_matches_the_per_folder_one(self):
        from documents.access import bulk_effective_access

        folders = list(Folder.objects.all())
        for user in (self.admin, self.manager, self.owner, self.auditor, self.viewer):
            bulk = bulk_effective_access(user, folders)
            for folder in folders:
                self.assertEqual(bulk[folder.id], folder.effective_access(user),
                                 f"{user.username} on {folder.name}")


class HiddenFolderIdTests(APITestBase):
    """A hidden folder must be answered exactly as a missing one, or a member learns which folder ids exist."""

    def test_a_document_patched_into_a_hidden_folder(self):
        # The owner may PATCH their document with only view on its folder.
        grant(self.tree.ctrl1, user=self.owner, level=VIEW)
        doc = make_doc(self.tree.ctrl1, self.owner)
        client = self.client_for(self.owner)
        hidden = self.tree.ctrl2.pk
        real = client.patch(f"/api/documents/{doc.pk}/", {"folder": hidden}, format="json")
        missing = client.patch(f"/api/documents/{doc.pk}/", {"folder": 999999}, format="json")
        assert_same_as_missing(self, real, missing, hidden)
        # A destination they can edit is still refused: the source is only view.
        grant(self.tree.ctrl2, user=self.owner, level=EDIT)
        refused = client.patch(f"/api/documents/{doc.pk}/", {"folder": self.tree.ctrl2.pk}, format="json")
        self.assertEqual(refused.status_code, 403)
        doc.refresh_from_db()
        self.assertEqual(doc.folder_id, self.tree.ctrl1.pk)

    def test_a_folder_made_under_a_hidden_parent(self):
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        client = self.client_for(self.owner)
        hidden = self.tree.ctrl2.pk
        real = client.post("/api/folders/", {"name": "Probe", "parent": hidden}, format="json")
        missing = client.post("/api/folders/", {"name": "Probe", "parent": 999999}, format="json")
        assert_same_as_missing(self, real, missing, hidden)
        visible = Folder.objects.create(name="Visible only")
        grant(visible, user=self.owner, level=VIEW)
        self.assertEqual(
            client.post("/api/folders/", {"name": "Child", "parent": visible.pk}, format="json").status_code, 403)
        made = client.post("/api/folders/", {"name": "Child", "parent": self.tree.ctrl1.pk}, format="json")
        self.assertEqual(made.status_code, 201, made.data)

    def test_a_folder_moved_under_a_hidden_parent(self):
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        client = self.client_for(self.owner)
        hidden = self.tree.root.pk
        real = client.patch(f"/api/folders/{self.tree.ctrl1.pk}/", {"parent": hidden}, format="json")
        missing = client.patch(f"/api/folders/{self.tree.ctrl1.pk}/", {"parent": 999999}, format="json")
        assert_same_as_missing(self, real, missing, hidden)
        self.assertEqual(Folder.objects.get(pk=self.tree.ctrl1.pk).parent_id, self.tree.cat.pk)
        # A folder they manage, moved under one they can only view, is still refused.
        grant(self.tree.ctrl1, user=self.owner, level=MANAGE)
        child = client.post("/api/folders/", {"name": "Scans", "parent": self.tree.ctrl1.pk}, format="json")
        self.assertEqual(child.status_code, 201, child.data)
        view_only = Folder.objects.create(name="View target")
        grant(view_only, user=self.owner, level=VIEW)
        refused = client.patch(f"/api/folders/{child.data['id']}/", {"parent": view_only.pk}, format="json")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(Folder.objects.get(pk=child.data["id"]).parent_id, self.tree.ctrl1.pk)

    def test_a_grant_made_on_or_moved_to_a_hidden_folder(self):
        client = self.client_for(self.owner)
        hidden = self.tree.root.pk
        body = {"user": self.viewer.pk, "access_level": "view"}
        real = client.post("/api/folder-permissions/", {"folder": hidden, **body}, format="json")
        missing = client.post("/api/folder-permissions/", {"folder": 999999, **body}, format="json")
        assert_same_as_missing(self, real, missing, hidden)
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        self.assertEqual(
            client.post("/api/folder-permissions/", {"folder": self.tree.ctrl1.pk, **body}, format="json").status_code,
            403)
        grant(self.tree.ctrl2, user=self.owner, level=MANAGE)
        made = client.post("/api/folder-permissions/", {"folder": self.tree.ctrl2.pk, **body}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        moved = client.patch(f"/api/folder-permissions/{made.data['id']}/", {"folder": hidden}, format="json")
        moved_missing = client.patch(f"/api/folder-permissions/{made.data['id']}/", {"folder": 999999}, format="json")
        assert_same_as_missing(self, moved, moved_missing, hidden)
        self.assertEqual(client.get(f"/api/folder-permissions/{made.data['id']}/").data["folder"], self.tree.ctrl2.pk)


class MoveTargetTypeTests(APITestBase):
    """JSON true is 1 and 1.5 truncated to 1, so either moved a document into a folder the caller never named."""

    def setUp(self):
        super().setUp()
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        grant(self.tree.ctrl2, user=self.owner, level=EDIT)
        self.doc = make_doc(self.tree.ctrl1, self.owner)
        self.client = self.client_for(self.owner)

    def move(self, folder):
        return self.client.post(f"/api/documents/{self.doc.pk}/move/", {"folder": folder}, format="json")

    def test_a_fraction_is_not_found(self):
        self.assertEqual(self.move(self.tree.ctrl2.pk + 0.5).status_code, 400)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.folder_id, self.tree.ctrl1.pk)

    def test_true_is_not_found(self):
        folder_one, _ = Folder.objects.get_or_create(pk=1, defaults={"name": "Pk one"})
        grant(folder_one, user=self.owner, level=EDIT)
        self.assertEqual(self.move(True).status_code, 400)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.folder_id, self.tree.ctrl1.pk)

    def test_a_whole_number_past_the_database_integer_is_not_found(self):
        # Django drops an out-of-range integer from an exact lookup before any
        # SQL, so this is "not found" on every database.
        self.assertEqual(self.move(2 ** 63).status_code, 400)
        response = self.client.get(f"/api/documents/{self.doc.pk}/versions/{2 ** 63}/download/")
        self.assertEqual(response.status_code, 400)

