"""0.9.5oc remediation, documents: FIL-01 to FIL-04, ROB-05 and ROB-07 (documents part)."""
from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts import tenancy
from accounts.models import Workspace
from documents import monitor
from documents.access import accessible_folder_ids, bulk_effective_access
from documents.models import Document, DocumentVersion, Folder, FormTemplate
from documents.tests_monitor import ClamdMixin
from testutils import APITestBase, grant, make_doc, make_roles, make_user, Tree


BAD = b"test-malware-marker"


def rows(response):
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


class FolderOwnershipTests(APITestBase):
    """FIL-01: ownership is manage on that folder only, in the id set and in effective_access alike."""

    def setUp(self):
        super().setUp()
        self.hr = Folder.objects.create(name="HR", owner=self.owner)
        self.inv = Folder.objects.create(name="Investigations", parent=self.hr)
        self.notes = make_doc(self.inv, self.manager, name="Whistleblower notes")
        self.c = self.client_for(self.owner)

    def test_the_owner_does_not_see_into_a_subfolder_they_were_never_granted(self):
        self.assertEqual(accessible_folder_ids(self.owner), {self.hr.id})
        found = self.c.get("/api/documents/?search=Whistleblower")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(rows(found), [])
        self.assertEqual(self.c.get(f"/api/documents/{self.notes.pk}/").status_code, 404)
        names = []

        def walk(nodes):
            for node in nodes:
                names.append(node["name"])
                walk(node["children"])

        walk(self.c.get("/api/folders/tree/").data)
        self.assertEqual(names, ["HR"])

    def test_the_lists_and_effective_access_agree_for_the_owner(self):
        folders = list(Folder.objects.all())
        levels = bulk_effective_access(self.owner, folders)
        seen = accessible_folder_ids(self.owner)
        for folder in folders:
            self.assertEqual(levels[folder.id] is not None, folder.id in seen, folder.name)
            self.assertEqual(levels[folder.id], folder.effective_access(self.owner), folder.name)

    def test_a_grant_below_an_owned_folder_still_opens_the_rest_of_that_branch(self):
        leaf = Folder.objects.create(name="Leaf", parent=self.inv)
        grant(self.hr, user=self.viewer)
        owned_inside = Folder.objects.create(name="Owned inside", parent=self.inv, owner=self.viewer)
        deeper = Folder.objects.create(name="Deeper", parent=owned_inside)
        self.assertEqual(accessible_folder_ids(self.viewer), {self.hr.id, self.inv.id, leaf.id, owned_inside.id,
                                                              deeper.id})

    def test_a_folder_the_owner_creates_is_theirs_to_open_and_use(self):
        made = self.c.post("/api/folders/", {"name": "Mine", "parent": self.hr.pk}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        self.assertEqual(made.data["owner"], self.owner.pk)
        self.assertEqual(self.c.get(f"/api/folders/{made.data['id']}/").status_code, 200)
        self.assertEqual(made.data["my_access"], "manage")
        listed = {f["id"] for f in rows(self.c.get("/api/folders/"))}
        self.assertIn(made.data["id"], listed)

    def test_edit_access_alone_does_not_make_the_creator_the_owner(self):
        grant(self.hr, user=self.viewer, level="edit")
        made = self.client_for(self.viewer).post("/api/folders/", {"name": "Sub", "parent": self.hr.pk}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        self.assertIsNone(made.data["owner"])
        self.assertEqual(made.data["my_access"], "edit")

    def test_manage_through_a_grant_does_not_make_the_creator_the_owner(self):
        given = grant(self.hr, user=self.viewer, level="manage")
        c = self.client_for(self.viewer)
        made = c.post("/api/folders/", {"name": "Renewals", "parent": self.hr.pk}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        self.assertIsNone(made.data["owner"])
        self.assertEqual(made.data["my_access"], "manage")
        given.delete()
        self.assertEqual(c.get(f"/api/folders/{made.data['id']}/").status_code, 404)
        self.assertNotIn(made.data["id"], {f["id"] for f in rows(c.get("/api/folders/"))})

    def test_an_auditor_who_owns_a_folder_cannot_create_in_it(self):
        Folder.objects.filter(pk=self.hr.pk).update(owner=self.auditor)
        before = Folder.objects.count()
        made = self.client_for(self.auditor).post("/api/folders/", {"name": "Nope", "parent": self.hr.pk},
                                                  format="json")
        self.assertEqual(made.status_code, 403)
        self.assertEqual(Folder.objects.count(), before)


class FolderPathVisibilityTests(APITestBase):
    """FIL-02: a path names only the folders the caller may view."""

    def setUp(self):
        super().setUp()
        self.falcon = Folder.objects.create(name="Project Falcon")
        self.contracts = Folder.objects.create(name="Contracts", parent=self.falcon)
        self.doc = make_doc(self.contracts, self.manager, name="Master agreement")
        grant(self.contracts, user=self.viewer)

    def test_a_grant_on_the_child_alone_does_not_reveal_the_parent_name(self):
        c = self.client_for(self.viewer)
        detail = c.get(f"/api/folders/{self.contracts.pk}/")
        self.assertEqual(detail.data["path"], "Contracts")
        self.assertEqual(rows(c.get("/api/folders/"))[0]["path"], "Contracts")
        document = c.get(f"/api/documents/{self.doc.pk}/")
        self.assertEqual(document.data["folder_path"], "Contracts")
        self.assertNotIn("Falcon", str(rows(c.get("/api/documents/"))))
        self.assertNotIn("Falcon", str(c.get("/api/documents/reviews/?days=90").data))

    def test_someone_who_can_see_the_whole_chain_gets_the_whole_path(self):
        admin = self.client_for(self.admin)
        self.assertEqual(admin.get(f"/api/folders/{self.contracts.pk}/").data["path"], "Project Falcon/Contracts")
        self.assertEqual(admin.get(f"/api/documents/{self.doc.pk}/").data["folder_path"],
                         "Project Falcon/Contracts")
        grant(self.falcon, user=self.owner)
        self.assertEqual(self.client_for(self.owner).get(f"/api/documents/{self.doc.pk}/").data["folder_path"],
                         "Project Falcon/Contracts")

    def test_the_evidence_routes_and_the_overdue_sample_clip_the_path_too(self):
        from compliance.models import Control, ControlEvidence

        ControlEvidence.objects.create(control=Control.objects.first(), document=self.doc, linked_by=self.manager)
        overdue = timezone.localdate() - timezone.timedelta(days=3)
        Document.objects.filter(pk=self.doc.pk).update(next_review_date=overdue)
        c = self.client_for(self.viewer)
        picks = [d for d in c.get("/api/control-evidence/choices/").data["documents"] if d["id"] == self.doc.pk]
        self.assertEqual(picks[0]["path"], "Contracts")
        links = rows(c.get(f"/api/control-evidence/?document={self.doc.pk}"))
        self.assertEqual([link["folder_path"] for link in links], ["Contracts"])
        sample = c.get("/api/analytics/summary/").data["overdue_sample"]
        self.assertEqual([d["folder_path"] for d in sample if d["id"] == self.doc.pk], ["Contracts"])
        self.assertEqual(rows(self.client_for(self.admin).get(f"/api/control-evidence/?document={self.doc.pk}"))[0]
                         ["folder_path"], "Project Falcon/Contracts")

    def test_another_workspace_never_contributes_a_name(self):
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-paths")
        with tenancy.scoped(beta):
            make_roles()
            Folder.objects.create(name="Beta secret")
        self.assertNotIn("Beta secret", str(self.client_for(self.admin).get("/api/folders/").data))


class ScanVersionsAndTemplatesTests(ClamdMixin, APITestBase):
    """FIL-03: the sweep opens archived versions and form templates, and each has its own quarantine."""

    def setUp(self):
        super().setUp()
        self.clamd.forced = None
        # The marker, not a real EICAR file: desktop antivirus deletes those from the temp folder mid-run.
        self.clamd.reply_for = lambda payload: (
            b"stream: Test.Marker FOUND\0" if BAD in payload else b"stream: OK\0")
        self.addCleanup(self.clamd.__dict__.pop, "reply_for", None)
        self.doc = make_doc(self.tree.ctrl1, self.manager, name="Policy", content=b"first bytes")
        self.old = DocumentVersion.objects.create(
            document=self.doc, version=1, uploaded_by=self.manager,
            file=ContentFile(BAD, name="old.bin"))
        self.template = FormTemplate.objects.create(
            name="Register", file=ContentFile(BAD, name="register.bin"))
        self.c = self.client_for(self.manager)

    def test_a_flagged_archived_version_is_refused_and_the_current_file_is_not(self):
        with self.scanning():
            counts = monitor.rescan(DocumentVersion.objects.all())
        self.assertEqual(counts["infected"], 1)
        self.old.refresh_from_db()
        self.doc.refresh_from_db()
        self.assertTrue(self.old.is_quarantined)
        self.assertIsNone(self.doc.quarantined_at)
        refused = self.c.get(f"/api/documents/{self.doc.pk}/versions/{self.old.pk}/download/")
        self.assertEqual(refused.status_code, 403)
        self.assertIn("quarantined", str(refused.data["detail"]))
        self.assertEqual(self.c.get(f"/api/documents/{self.doc.pk}/download/").status_code, 200)
        self.assertTrue(self.c.get(f"/api/documents/{self.doc.pk}/versions/").data[0]["quarantined"])

    def test_a_flagged_form_template_is_refused(self):
        self.assertEqual(self.c.get(f"/api/form-templates/{self.template.pk}/download/").status_code, 200)
        with self.scanning():
            monitor.rescan(FormTemplate.objects.all())
        self.assertEqual(self.c.get(f"/api/form-templates/{self.template.pk}/download/").status_code, 403)

    def test_the_command_sweeps_documents_versions_and_templates(self):
        out = StringIO()
        with self.scanning(), self.assertRaises(CommandError):
            call_command("scan_evidence", "--all", stdout=out)
        self.old.refresh_from_db()
        self.template.refresh_from_db()
        self.doc.refresh_from_db()
        self.assertTrue(self.old.is_quarantined)
        self.assertTrue(self.template.is_quarantined)
        self.assertFalse(self.doc.is_quarantined)
        self.assertIn("Files scanned: 3", out.getvalue())
        self.assertIn("Quarantined files now: 2", out.getvalue())

    def test_a_clean_answer_later_releases_a_version_and_the_sweep_runs_with_no_workspace_active(self):
        with self.scanning():
            monitor.rescan(DocumentVersion.objects.all())
            self.old.file.save("clean.bin", ContentFile(b"harmless"))
            DocumentVersion.objects.filter(pk=self.old.pk).update(quarantined_at=timezone.now())
            with tenancy.unscoped():
                self.assertEqual(monitor.scan_document(DocumentVersion.objects.get(pk=self.old.pk)), "clean")
        self.old.refresh_from_db()
        self.assertFalse(self.old.is_quarantined)

    def test_a_replaced_template_file_starts_with_a_clean_slate(self):
        with self.scanning():
            monitor.rescan(FormTemplate.objects.all())
            put = self.c.patch(f"/api/form-templates/{self.template.pk}/",
                               {"file": SimpleUploadedFile("fresh.txt", b"fresh")}, format="multipart")
        self.assertEqual(put.status_code, 200, put.data)
        self.template.refresh_from_db()
        self.assertFalse(self.template.is_quarantined)
        self.assertEqual(self.template.scan_status, "clean")

    def test_an_auditor_cannot_download_a_template(self):
        denied = self.client_for(self.auditor).get(f"/api/form-templates/{self.template.pk}/download/")
        self.assertEqual(denied.status_code, 403)


@override_settings(CLAMAV_ENABLED=True)
class StaleVerdictTests(APITestBase):
    """FIL-04: a verdict is written only to the bytes that were scanned, and a clean one never undoes a quarantine."""

    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, self.manager, name="Contested", content=b"version one")

    def test_a_file_replaced_during_the_scan_keeps_its_own_state(self):
        loaded = Document.objects.get(pk=self.doc.pk)

        def replaced_meanwhile(subject):
            Document.objects.filter(pk=subject.pk).update(file="documents/two.txt", version=2, scan_status="clean")
            return "infected", "Test.Sig", mock.Mock(signature="Test.Sig")

        with mock.patch.object(monitor, "_verdict", side_effect=replaced_meanwhile):
            monitor.scan_document(loaded)
        row = Document.objects.get(pk=self.doc.pk)
        self.assertEqual((row.scan_status, row.quarantined_at, row.scan_signature, row.version), ("clean", None, "", 2))

    def test_a_clean_result_does_not_clear_a_quarantine_recorded_after_it_began(self):
        loaded = Document.objects.get(pk=self.doc.pk)
        flagged_at = timezone.now()

        def flagged_meanwhile(subject):
            Document.objects.filter(pk=subject.pk).update(
                quarantined_at=flagged_at, scan_status="infected", scan_signature="Other.Sig")
            return "clean", "", None

        with mock.patch.object(monitor, "_verdict", side_effect=flagged_meanwhile):
            self.assertEqual(monitor.scan_document(loaded), "infected")
        row = Document.objects.get(pk=self.doc.pk)
        self.assertEqual((row.quarantined_at, row.scan_status, row.scan_signature),
                         (flagged_at, "infected", "Other.Sig"))

    def test_an_ordinary_infected_and_released_cycle_still_works(self):
        loaded = Document.objects.get(pk=self.doc.pk)
        hit = ("infected", "Test.Sig", mock.Mock(signature="Test.Sig"))
        with mock.patch.object(monitor, "_verdict", return_value=hit), \
                mock.patch("notifications.webhooks.post_event"):
            self.assertEqual(monitor.scan_document(loaded), "infected")
        self.assertIsNotNone(Document.objects.get(pk=self.doc.pk).quarantined_at)
        with mock.patch.object(monitor, "_verdict", return_value=("clean", "", None)):
            self.assertEqual(monitor.scan_document(Document.objects.get(pk=self.doc.pk)), "clean")
        self.assertIsNone(Document.objects.get(pk=self.doc.pk).quarantined_at)


class VersioningAndReviewTests(APITestBase):
    """ROB-05: new_version allocates under a lock and maps a clash to 409; mark_reviewed saves its own fields only."""

    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, self.manager, name="Policy v1", content=b"one")
        self.c = self.client_for(self.manager)

    def upload(self, body=b"two"):
        return self.c.post(f"/api/documents/{self.doc.pk}/new_version/",
                           {"file": SimpleUploadedFile("next.txt", body)}, format="multipart")

    def test_a_version_row_left_by_a_crashed_request_does_not_block_later_uploads(self):
        DocumentVersion.objects.create(document=self.doc, version=1, file=self.doc.file, uploaded_by=self.manager)
        made = self.upload()
        self.assertEqual(made.status_code, 200, made.data)
        self.assertEqual(made.data["version"], 2)
        self.assertEqual(self.doc.versions.count(), 1)
        third = self.upload(b"three")
        self.assertEqual(third.data["version"], 3)
        self.assertEqual(sorted(self.doc.versions.values_list("version", flat=True)), [1, 2])

    def test_a_clash_on_the_version_number_is_a_409_and_changes_nothing(self):
        with mock.patch.object(DocumentVersion.objects.__class__, "get_or_create", side_effect=IntegrityError("dup")):
            clash = self.upload()
        self.assertEqual(clash.status_code, 409)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.version, 1)

    def test_two_uploads_in_a_row_number_the_versions_one_after_the_other(self):
        self.assertEqual(self.upload().data["version"], 2)
        self.assertEqual(self.upload(b"x").data["version"], 3)
        self.assertEqual(sorted(self.doc.versions.values_list("version", flat=True)), [1, 2])

    def test_marking_reviewed_keeps_a_title_edited_a_moment_earlier(self):
        stale = Document.objects.get(pk=self.doc.pk)
        Document.objects.filter(pk=self.doc.pk).update(name="Policy v2", description="edited")
        with mock.patch("documents.views.DocumentViewSet.get_object", return_value=stale):
            done = self.c.post(f"/api/documents/{self.doc.pk}/mark_reviewed/")
        self.assertEqual(done.status_code, 200, done.data)
        row = Document.objects.get(pk=self.doc.pk)
        self.assertEqual((row.name, row.description), ("Policy v2", "edited"))
        self.assertEqual(row.last_reviewed, timezone.localdate())
        self.assertEqual(row.status, "approved")

    def test_an_auditor_cannot_version_or_mark_reviewed(self):
        grant(self.tree.ctrl1, user=self.auditor, level="manage")
        c = self.client_for(self.auditor)
        self.assertEqual(c.post(f"/api/documents/{self.doc.pk}/mark_reviewed/").status_code, 403)
        self.assertEqual(c.post(f"/api/documents/{self.doc.pk}/new_version/",
                                {"file": SimpleUploadedFile("a.txt", b"a")}, format="multipart").status_code, 403)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.version, 1)


class ListCostTests(APITestBase):
    """ROB-07 (documents part): the reviews list filters in SQL and a folder path costs no query per hop."""

    def deep_docs(self, count, depth=6):
        parent = None
        for level in range(depth):
            parent = Folder.objects.create(name=f"Level {level} of {Folder.objects.count()}", parent=parent)
        for i in range(count):
            make_doc(parent, self.manager, name=f"Dated {i}", days=10 + i)
        return parent

    def reviews_queries(self, user):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client_for(user).get("/api/documents/reviews/?days=365")
        self.assertEqual(response.status_code, 200)
        return len(ctx), response

    def test_the_reviews_list_costs_the_same_for_three_files_and_thirty(self):
        self.deep_docs(3)
        few, _ = self.reviews_queries(self.admin)
        self.deep_docs(30)
        many, response = self.reviews_queries(self.admin)
        self.assertEqual(len(response.data), 33)
        self.assertLessEqual(many, few + 2)

    def test_the_horizon_and_the_order_come_from_the_database(self):
        folder = self.tree.ctrl1
        make_doc(folder, self.manager, name="Soon", days=5)
        make_doc(folder, self.manager, name="Later", days=60)
        make_doc(folder, self.manager, name="Far", days=400)
        make_doc(folder, self.manager, name="Overdue", days=-3)
        got = self.client_for(self.admin).get("/api/documents/reviews/?days=90").data
        self.assertEqual([d["name"] for d in got], ["Overdue", "Soon", "Later"])

    def test_the_list_is_capped(self):
        for i in range(4):
            make_doc(self.tree.ctrl1, self.manager, name=f"Capped {i}", days=i + 1)
        with mock.patch("documents.views.REVIEWS_CAP", 2):
            got = self.client_for(self.admin).get("/api/documents/reviews/?days=90").data
        self.assertEqual([d["name"] for d in got], ["Capped 0", "Capped 1"])

    def test_the_grant_list_asks_a_fixed_number_of_questions_however_many_folders_exist(self):
        grant(self.tree.ctrl1, user=self.owner, level="manage")

        def cost():
            with CaptureQueriesContext(connection) as ctx:
                response = self.client_for(self.owner).get("/api/folder-permissions/")
            self.assertEqual(response.status_code, 200)
            return len(ctx), response

        few, _ = cost()
        for i in range(25):
            Folder.objects.create(name=f"Extra {i}", parent=self.tree.cat)
        many, response = cost()
        self.assertEqual(many, few)
        self.assertEqual([g["folder"] for g in rows(response)], [self.tree.ctrl1.pk])

    def test_the_grant_list_still_shows_only_folders_the_caller_manages(self):
        grant(self.tree.ctrl1, user=self.owner, level="edit")
        grant(self.tree.ctrl2, user=self.viewer, level="view")
        self.assertEqual(rows(self.client_for(self.owner).get("/api/folder-permissions/")), [])
        owned = Folder.objects.create(name="Owned", owner=self.owner)
        grant(owned, user=self.viewer, level="view")
        self.assertEqual([g["folder"] for g in rows(self.client_for(self.owner).get("/api/folder-permissions/"))],
                         [owned.pk])
