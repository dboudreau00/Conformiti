"""0.9.5: the bundled verifier refuses an unsigned bundle, and the public key
list does not enumerate the organisations on an installation."""
import subprocess
import sys
import tempfile
from pathlib import Path

from accounts import tenancy
from accounts.models import Workspace
from testutils import APITestBase

from .tests import PackageTestBase


def run_verifier(root, *flags):
    return subprocess.run([sys.executable, "verify.py", *flags, "."], cwd=root,
                          capture_output=True, text=True, timeout=300)


class UnsignedBundleTests(PackageTestBase):
    """Strip the signatures, rewrite the file list to match, and the old
    verifier said OK with exit 0. Every checksum agreed with itself; nothing
    proved who made it. Automation keyed on the exit code accepted a forgery.
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
            self.assertNotIn("OK —", r.stdout)

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
    """``/api/signing-keys/`` is public because a public key is for
    publishing. It must not also publish the list of tenants."""

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
