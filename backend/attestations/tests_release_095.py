"""0.9.5: the bundled verifier refuses an unsigned bundle, and the public key
list does not enumerate the organisations on an installation. 0.9.5oa: an id
the caller cannot read, in a PBC line or an attachment, answers as an id that
is not there."""
import subprocess
import sys
import tempfile
from pathlib import Path

from accounts import tenancy
from accounts.models import Workspace
from attestations.models import EvidencePackage, PackageControl
from documents.models import VIEW
from testutils import APITestBase, assert_same_as_missing, grant, make_doc

from .tests import PackageTestBase
from .tests_pbc import PbcBase


def run_verifier(root, *flags):
    return subprocess.run([sys.executable, "verify.py", *flags, "."], cwd=root,
                          capture_output=True, text=True, timeout=300)


class UnsignedBundleTests(PackageTestBase):
    """A bundle with its signatures stripped and its file list rewritten to
    match must not verify with exit 0. Every checksum agrees with itself but
    nothing proves who made it, and automation keyed on the exit code would
    accept a forgery.
    """

    def export(self):
        import io
        import zipfile

        self.add_control()
        self.seal()
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        return zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)
                                          if r.streaming else r.content))

    def test_an_intact_bundle_verifies_with_exit_0(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            ok = run_verifier(tmp)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn("Both signatures verify", ok.stdout)

    def test_a_bundle_with_its_signatures_stripped_is_not_ok(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            root = Path(tmp)
            (root / "manifest.sig").unlink()
            (root / "SHA256SUMS.sig").unlink()
            # The attacker also drops the two signature files from the list,
            # so no checksum mismatch is left to catch them.
            sums = root / "SHA256SUMS"
            sums.write_text("".join(
                line for line in sums.read_text().splitlines(keepends=True)
                if not line.rstrip().endswith((".sig",))))
            r = run_verifier(tmp)
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            self.assertIn("UNSIGNED", r.stdout)
            self.assertNotIn("OK:", r.stdout)

            # Accepting an unsigned bundle is a deliberate act, and says so.
            allowed = run_verifier(tmp, "--allow-unsigned")
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertIn("does not prove their origin", allowed.stdout)

    def test_only_the_file_list_signature_stripped_is_not_ok_either(self):
        """The manifest signature alone covers what was sealed; the auditor's
        conclusions written afterwards are covered only by SHA256SUMS.sig."""
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            root = Path(tmp)
            (root / "SHA256SUMS.sig").unlink()
            sums = root / "SHA256SUMS"
            sums.write_text("".join(
                line for line in sums.read_text().splitlines(keepends=True)
                if "SHA256SUMS.sig" not in line))
            r = run_verifier(tmp)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("SHA256SUMS.sig missing", r.stdout)

    def test_an_unknown_flag_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            zf = self.export()
            zf.extractall(tmp)
            r = run_verifier(tmp, "--skip-everything")
        self.assertEqual(r.returncode, 2)


class SigningKeyDirectoryTests(APITestBase):
    """``/api/signing-keys/`` is public, so an auditor can compare keys. It
    must not also publish the list of tenants."""

    def test_single_workspace_answers_without_a_slug(self):
        r = self.client_for().get("/api/signing-keys/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("keys", r.data)

    def test_several_workspaces_require_a_slug_and_name_none(self):
        Workspace.objects.create(name="Beta Ltd", slug="beta-ltd")
        Workspace.objects.create(name="Gamma Inc", slug="gamma-inc")
        r = self.client_for().get("/api/signing-keys/")
        self.assertEqual(r.status_code, 400)
        body = str(r.data)
        self.assertNotIn("beta-ltd", body)
        self.assertNotIn("gamma-inc", body)
        self.assertNotIn("Beta Ltd", body)

        named = self.client_for().get("/api/signing-keys/?workspace=beta-ltd")
        self.assertEqual(named.status_code, 200)
        self.assertEqual(named.data["workspace"], "beta-ltd")
        for key in named.data["keys"]:
            self.assertEqual(key["workspace"], "beta-ltd")

    def test_an_archived_workspace_does_not_count(self):
        Workspace.objects.create(name="Old Co", slug="old-co", is_active=False)
        r = self.client_for().get("/api/signing-keys/")
        self.assertEqual(r.status_code, 200)
        with tenancy.unscoped():
            self.assertEqual(Workspace.objects.filter(is_active=True).count(), 1)

    def test_and_the_archived_one_is_not_in_the_answer_either(self):
        """0.9.5f, L-2. Archived organisations are deliberately not counted:
        an installation that has retired a workspace is still single-tenant
        and should not have to name itself. The unnamed answer must still
        not list every key on the server (scoping to None is unscoped), or
        the organisations that had left would be disclosed by the route that
        publishes one public key."""
        from attestations.models import SigningKey

        old = Workspace.objects.create(name="Old Co", slug="old-co", is_active=False)
        with tenancy.scoped(old):
            SigningKey.objects.create(workspace=old, key_id="deadbeefdeadbeef",
                                      public_key="x" * 44, label="Old Co")
        body = str(self.client_for().get("/api/signing-keys/").data)
        self.assertNotIn("old-co", body)
        self.assertNotIn("Old Co", body)
        self.assertNotIn("deadbeefdeadbeef", body)


class PbcHiddenIdTests(PbcBase):
    """A PBC line's control and an attachment's document and request accepted
    any row in the workspace, and the view then answered 403, which confirmed
    the id."""

    def setUp(self):
        super().setUp()
        raised = self.raise_line(self.auditor_client).data
        self.line = self.manager_client.patch(
            f"/api/pbc-requests/{raised['id']}/", {"assignee": self.owner.pk}, format="json").data
        self.hidden = make_doc(self.tree.ctrl2, owner=self.manager, name="Hidden report", content=b"secret")
        grant(self.tree.ctrl1, user=self.owner, level=VIEW)

    def test_a_control_of_a_package_the_auditor_cannot_read(self):
        other = EvidencePackage.objects.create(name="Draft elsewhere", created_by=self.manager)
        row = PackageControl.objects.create(package=other, control_ref="ZZ", title="Hidden control")
        real = self.raise_line(self.auditor_client, package_control=row.pk)
        missing = self.raise_line(self.auditor_client, package_control=999999)
        assert_same_as_missing(self, real, missing, row.pk)
        own = self.package.controls.first()
        created = self.raise_line(self.auditor_client, package_control=own.pk)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["control_ref"], own.control_ref)
        line = self.raise_line(self.auditor_client).data
        patched = self.auditor_client.patch(f"/api/pbc-requests/{line['id']}/", {"package_control": row.pk},
                                            format="json")
        patched_missing = self.auditor_client.patch(f"/api/pbc-requests/{line['id']}/",
                                                    {"package_control": 999999}, format="json")
        assert_same_as_missing(self, patched, patched_missing, row.pk)

    def test_a_document_in_a_folder_the_assignee_cannot_see(self):
        attached = self.owner_client.post("/api/pbc-items/", {"request": self.line["id"], "document": self.doc.pk},
                                          format="json")
        self.assertEqual(attached.status_code, 201, attached.data)
        real = self.owner_client.post("/api/pbc-items/", {"request": self.line["id"], "document": self.hidden.pk},
                                      format="json")
        missing = self.owner_client.post("/api/pbc-items/", {"request": self.line["id"], "document": 999999},
                                         format="json")
        assert_same_as_missing(self, real, missing, self.hidden.pk)

    def test_a_request_the_caller_cannot_read(self):
        other = self.raise_line(self.manager_client).data
        real = self.owner_client.post("/api/pbc-items/", {"request": other["id"], "document": self.doc.pk},
                                      format="json")
        missing = self.owner_client.post("/api/pbc-items/", {"request": 999999, "document": self.doc.pk},
                                         format="json")
        assert_same_as_missing(self, real, missing, other["id"])
