"""0.9.5: an edited review date starts the reminders again, and the folder
tree costs a fixed number of queries however many folders it has."""
from django.utils import timezone

from documents.models import EDIT, VIEW, Document, Folder
from notifications.tasks import OVERDUE, run_review_scan
from testutils import APITestBase, grant, make_doc


class ReviewClockTests(APITestBase):
    def setUp(self):
        super().setUp()
        # An annual policy last reviewed thirteen months ago: the stored
        # next_review_date is exactly what the cadence computes from that,
        # so an edit that does not touch the clock recomputes the same date.
        self.doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Policy", days=-3)
        self.doc.last_reviewed = timezone.localdate() - timezone.timedelta(days=395)
        self.doc.compute_next_review()
        self.doc.save()
        self.assertLess(self.doc.next_review_date, timezone.localdate())

    def test_editing_the_review_date_clears_the_reminders_sent(self):
        # The overdue notice has gone out and the sentinel is recorded.
        self.assertEqual(run_review_scan(), 1)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.reminders_sent, [OVERDUE])
        self.assertEqual(self.doc.status, Document.Status.EXPIRED)

        # The owner corrects the last-reviewed date through the ordinary
        # PATCH. The clock moves; the record of windows sent for the OLD
        # clock used to stay, so nothing ever fired for the new one.
        r = self.client_for(self.manager).patch(
            f"/api/documents/{self.doc.pk}/",
            {"last_reviewed": timezone.localdate().isoformat()}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.doc.refresh_from_db()
        self.assertGreater(self.doc.next_review_date, timezone.localdate())
        self.assertEqual(self.doc.reminders_sent, [])

        # And when that new date passes, the notice fires again.
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
    """The tree ran an access walk and a count per node. Fifty folders were
    a hundred queries; the bell and the package list are the same class."""

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

