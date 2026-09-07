"""Regression tests for the 0.9.0 adversarial review.

Each test names the defect it locks shut. See REVIEW_090.md for the full set
of findings; these cover the ones remediated in this pass.
"""
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from documents.models import Document

from .models import PackageControl, PackageEvidence
from .tests import PackageTestBase


class SealedManifestTests(PackageTestBase):
    """A sealed package's snapshotted fields are what the signature covers."""

    def setUp(self):
        super().setUp()
        self.add_control()  # pins today's visible evidence for the control
        self.row = PackageControl.objects.get(package=self.package)
        self.evidence = PackageEvidence.objects.get(package_control=self.row)
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        self.auditor_client = self.client_for(self.auditor)

    def test_a_snapshot_field_cannot_ride_along_with_a_conclusion(self):
        """The auditor's conclusion and a manifest field in one PATCH used to
        save the manifest field without ever reaching assert_open."""
        before = self.row.population_size
        r = self.auditor_client.patch(
            f"/api/package-controls/{self.row.pk}/",
            {"design_conclusion": "no_exceptions", "population_size": 4242},
            format="json")
        self.assertEqual(r.status_code, 403, r.data)
        self.row.refresh_from_db()
        self.assertEqual(self.row.population_size, before)
        self.assertEqual(self.row.design_conclusion, "pending")

    def test_a_refused_mixed_write_commits_nothing(self):
        """The management response is the organisation's. An auditor sending
        it alongside their own conclusion used to have the conclusion
        committed before the 403 fired."""
        r = self.auditor_client.patch(
            f"/api/package-controls/{self.row.pk}/",
            {"design_conclusion": "no_exceptions", "management_response": "Forged"},
            format="json")
        self.assertEqual(r.status_code, 403, r.data)
        self.row.refresh_from_db()
        self.assertEqual(self.row.management_response, "")
        self.assertEqual(self.row.design_conclusion, "pending")

    def test_a_pinned_artefact_cannot_be_repointed(self):
        """Re-pointing skipped the folder-permission check that pinning
        performs, so it read any document in the workspace."""
        secret = make_secret_doc(self)
        r = self.manager_client.patch(
            f"/api/package-evidence/{self.evidence.pk}/",
            {"document": secret.pk}, format="json")
        self.assertIn(r.status_code, (400, 403), r.data)
        self.evidence.refresh_from_db()
        self.assertEqual(self.evidence.document_id, self.doc.pk)

    def test_a_sample_row_needs_a_reason_to_be_touched(self):
        """A body with neither a result nor an item field met no check."""
        r = self.manager_client.post("/api/package-samples/", {
            "package_control": self.row.pk, "identifier": "S-1"}, format="json")
        # Sealed: the organisation cannot add items, the auditor can.
        if r.status_code != 201:
            r = self.auditor_client.post("/api/package-samples/", {
                "package_control": self.row.pk, "identifier": "S-1"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        sample = r.data["id"]
        viewer = self.client_for(self.viewer)
        self.assertIn(viewer.patch(f"/api/package-samples/{sample}/",
                                   {"package_control": self.row.pk}, format="json").status_code,
                      (403, 404))


def make_secret_doc(case):
    """A document in a folder the assembler has no grant on."""
    doc = Document(folder=case.tree.ctrl2, name="Board minutes", owner=case.admin,
                   created_by=case.admin)
    doc.file.save("secret.txt", ContentFile(b"not for the auditor"), save=False)
    doc.save()
    return doc


class EvidenceByteTests(PackageTestBase):
    """Replacing a document's bytes is `new_version`'s job, not PATCH's."""

    def test_patching_a_file_is_refused(self):
        """A multipart PATCH replaced the stored bytes with no folder-edit
        check, no malware scan, no archived version and no version bump."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        before = self.doc.version
        r = self.manager_client.patch(
            f"/api/documents/{self.doc.pk}/",
            {"file": SimpleUploadedFile("swapped.txt", b"unscanned bytes")},
            format="multipart")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("new_version", str(r.data))
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.version, before)
        self.assertEqual(self.doc.file.read(), b"policy bytes")

    def test_taking_folder_ownership_needs_manage(self):
        """The owner IS a manager, so granting yourself ownership with only
        edit access was a self-service promotion."""
        from documents.models import EDIT, FolderPermission

        folder = self.tree.ctrl2
        FolderPermission.objects.create(folder=folder, user=self.owner, access_level=EDIT)
        r = self.client_for(self.owner).patch(
            f"/api/folders/{folder.pk}/", {"owner": self.owner.pk}, format="json")
        self.assertEqual(r.status_code, 403, r.data)
        folder.refresh_from_db()
        self.assertNotEqual(folder.owner_id, self.owner.pk)


class ManifestIdentityTests(PackageTestBase):
    """One signing key serves the installation, so the signed bytes have to
    say which organisation produced the bundle."""

    def test_the_sealed_manifest_names_the_workspace(self):
        import json

        self.add_control()
        self.seal()
        manifest = json.loads(self.package.manifest_json)
        self.assertEqual(manifest["manifest_version"], 4)
        self.assertEqual(manifest["package"]["workspace"]["slug"], "default")
