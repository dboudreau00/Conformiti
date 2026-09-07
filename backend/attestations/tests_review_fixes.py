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


class BundleSignatureCoverageTests(PackageTestBase):
    """The signature has to cover what the auditor actually reads.

    manifest.sig is made at seal and covers manifest.json alone; the
    conclusions land in controls.csv and samples.csv afterwards. Rewriting
    those used to leave verify.py printing VALID.
    """

    def export(self):
        import io as _io
        import zipfile

        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200, r.status_code)
        return zipfile.ZipFile(_io.BytesIO(b"".join(r.streaming_content)
                                           if r.streaming else r.content))

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()

    def test_the_bundle_carries_a_signature_over_its_file_list(self):
        zf = self.export()
        names = set(zf.namelist())
        self.assertIn("SHA256SUMS", names)
        self.assertIn("SHA256SUMS.sig", names)
        self.assertIn("sums-key.pub", names)
        # Everything the auditor reads is inside SHA256SUMS, so signing it
        # covers them transitively.
        listed = {line.split("  ", 1)[1]
                  for line in zf.read("SHA256SUMS").decode().splitlines() if line.strip()}
        for member in ("manifest.json", "controls.csv", "samples.csv", "trail.csv"):
            self.assertIn(member, listed)

    def test_rewriting_the_conclusions_is_caught(self):
        import base64
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            root = Path(tmp)
            # A clean bundle verifies.
            ok = subprocess.run([sys.executable, "verify.py", "."], cwd=root,
                                capture_output=True, text=True, timeout=300)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("over SHA256SUMS", ok.stdout)

            # Rewrite the auditor's workpaper and regenerate the file list to
            # match — the whole point of signing SHA256SUMS is that this fails.
            import hashlib

            controls = root / "controls.csv"
            controls.write_bytes(controls.read_bytes() + b"\nforged,row\n")
            sums = root / "SHA256SUMS"
            rebuilt = []
            for line in sums.read_text().splitlines():
                if not line.strip():
                    continue
                _digest, name = line.split("  ", 1)
                target = root / name
                new = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else _digest
                rebuilt.append(f"{new}  {name}")
            sums.write_text("\n".join(rebuilt) + "\n")

            bad = subprocess.run([sys.executable, "verify.py", "."], cwd=root,
                                 capture_output=True, text=True, timeout=300)
            self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
            self.assertIn("SHA256SUMS SIGNATURE DOES NOT VERIFY", bad.stdout)

    def test_a_file_added_to_the_bundle_is_reported(self):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            (Path(tmp) / "extra-evidence.txt").write_text("slipped in")
            r = subprocess.run([sys.executable, "verify.py", "."], cwd=tmp,
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("not listed in SHA256SUMS", r.stdout)


class PerWorkspaceKeyTests(PackageTestBase):
    """Each organisation signs with its own key, so the fingerprint an auditor
    is told to expect identifies the client, not the installation."""

    def test_two_workspaces_sign_with_different_keys(self):
        from accounts import tenancy
        from accounts.models import Workspace

        from . import signing

        root = signing.load_private_key(create=True)
        self.assertIsNotNone(root, "the test settings should configure a signing key")

        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-keys")
        with tenancy.scoped(tenancy.current()):
            here = signing.current_key_info(create=True)["key_id"]
        with tenancy.scoped(beta):
            there = signing.current_key_info(create=True)["key_id"]
        self.assertTrue(here and there)
        self.assertNotEqual(here, there, "each workspace needs its own key")

        # Derivation is deterministic: the same workspace always gets the same
        # key, so a published fingerprint stays valid across restarts.
        with tenancy.scoped(beta):
            self.assertEqual(signing.current_key_info(create=True)["key_id"], there)

    def test_a_sealed_package_is_signed_by_its_own_workspace_key(self):
        from accounts import tenancy

        from . import signing

        self.add_control()
        self.seal()
        self.package.refresh_from_db()
        self.assertTrue(self.package.signing_key_id)
        with tenancy.scoped(tenancy.current()):
            self.assertEqual(self.package.signing_key_id,
                             signing.current_key_info(create=True)["key_id"])
        self.assertEqual(signing.signature_status(self.package), "valid")

    def test_the_published_key_list_can_be_asked_for_one_organisation(self):
        self.add_control()
        self.seal()
        r = self.client_for(self.manager).get("/api/signing-keys/", {"workspace": "default"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["workspace"], "default")
        self.assertTrue(any(k["current"] for k in r.data["keys"]))
        self.assertEqual(self.client_for(self.manager).get(
            "/api/signing-keys/", {"workspace": "nope"}).status_code, 404)
