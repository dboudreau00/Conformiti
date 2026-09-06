"""Detached signatures: the key lives in a file, the seal signs the manifest,
the bundle carries signature and key, the shipped stdlib verifier agrees with
the cryptography library, and rotation keeps old packages verifying."""
import base64
import io
import json
import os
import tempfile
import zipfile
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from attestations import signing, verifier
from attestations.models import EvidencePackage, SigningKey
from attestations.tests import ASSERTION, PackageTestBase


class SigningKeyMixin:
    """A throwaway key file per test class."""

    @classmethod
    def setUpClass(cls):
        cls._keydir = tempfile.mkdtemp(prefix="conformiti-signing-")
        cls._key_override = override_settings(
            SIGNING_ENABLED=True, SIGNING_KEY="",
            SIGNING_KEY_FILE=os.path.join(cls._keydir, "package_signing_key"))
        cls._key_override.enable()
        signing._cache.update(path=None, mtime=None, key=None)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._key_override.disable()
        signing._cache.update(path=None, mtime=None, key=None)


class VerifierVectorTests(PackageTestBase):
    def test_the_stdlib_ed25519_matches_rfc_8032_test_1(self):
        public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertTrue(verifier.ed25519_verify(public, b"", signature))
        self.assertFalse(verifier.ed25519_verify(public, b"x", signature))
        self.assertFalse(verifier.ed25519_verify(public, b"", signature[:-1] + b"\x00"))
        self.assertFalse(verifier.ed25519_verify(b"\x00" * 32, b"", signature))

    def test_the_stdlib_verifier_agrees_with_the_library_on_fresh_keys(self):
        from cryptography.hazmat.primitives.asymmetric import ed25519
        for _ in range(3):
            key = ed25519.Ed25519PrivateKey.generate()
            msg = os.urandom(200)
            sig = key.sign(msg)
            pub = signing.public_raw(key.public_key())
            self.assertTrue(verifier.ed25519_verify(pub, msg, sig))
            self.assertFalse(verifier.ed25519_verify(pub, msg + b"!", sig))
            # And the PEM the bundle carries decodes to the same raw key.
            self.assertEqual(verifier.read_public_key(signing.public_pem(key.public_key())), pub)


class SealSigningTests(SigningKeyMixin, PackageTestBase):
    def setUp(self):
        super().setUp()
        self.add_control()

    def test_sealing_signs_the_manifest_with_a_file_key_created_on_first_use(self):
        from django.conf import settings as live
        # Another test in this class may already have created the class's key
        # file; start from none so first-use generation is what is exercised.
        if os.path.exists(live.SIGNING_KEY_FILE):
            os.remove(live.SIGNING_KEY_FILE)
        signing._cache.update(path=None, mtime=None, key=None)
        r = self.seal()
        self.assertTrue(os.path.exists(live.SIGNING_KEY_FILE))
        self.assertEqual(oct(os.stat(live.SIGNING_KEY_FILE).st_mode & 0o777)[-3:],
                         "600" if os.name != "nt" else oct(os.stat(live.SIGNING_KEY_FILE).st_mode & 0o777)[-3:])
        self.assertEqual(len(self.package.signing_key_id), 16)
        self.assertTrue(self.package.manifest_signature)
        self.assertEqual(r.data["signing_key_id"], self.package.signing_key_id)
        self.assertTrue(signing.verify_bytes(self.package.manifest_json.encode(),
                                             self.package.manifest_signature, self.package.signing_public_key))
        self.assertEqual(signing.signature_status(self.package), "valid")
        # Registered as the current key, and published.
        row = SigningKey.objects.get()
        self.assertEqual((row.key_id, row.retired_at), (self.package.signing_key_id, None))
        pub = APIClient().get("/api/signing-keys/").data
        self.assertEqual(pub["current"]["key_id"], row.key_id)
        self.assertEqual(pub["keys"][0]["fingerprint"], signing.fingerprint(row.public_key))
        # The seal entry says so.
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action="seal", detail__contains=f"signed key={row.key_id}").exists())

    def test_the_signature_endpoint_and_verify_report_it(self):
        self.seal()
        sig = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/signature/").data
        self.assertEqual((sig["signed"], sig["algorithm"], sig["status"]), (True, "Ed25519", "valid"))
        self.assertEqual(sig["fingerprint"][:16], sig["key_id"])
        v = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/verify/").data
        self.assertEqual((v["ok"], v["signature"]), (True, "valid"))
        # A tampered manifest is caught by verify, whatever the file digests say.
        EvidencePackage.objects.filter(pk=self.package.pk).update(
            manifest_json=self.package.manifest_json.replace("SOC 2 fieldwork", "SOC 2 fieldwerk"))
        v = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/verify/").data
        self.assertEqual((v["ok"], v["signature"]), (False, "invalid"))

    def test_the_bundle_carries_the_signature_and_the_shipped_verifier_checks_it(self):
        self.seal()
        self.issue_to(self.auditor)
        r = self.client_for(self.auditor).get(f"/api/evidence-packages/{self.package.pk}/export/")
        zf = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
        names = set(zf.namelist())
        self.assertIn("manifest.sig", names)
        self.assertIn("signing-key.pub", names)
        self.assertIn("SIGNATURE", zf.read("README.txt").decode())
        self.assertIn(self.package.signing_key_id, zf.read("README.txt").decode())
        with tempfile.TemporaryDirectory() as root:
            zf.extractall(root)
            out = StringIO()
            import contextlib
            with contextlib.redirect_stdout(out):
                code = verifier.main(root)
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("signature    : VALID", out.getvalue())
            self.assertIn(self.package.signing_key_id, out.getvalue())
            # Alter the manifest: the checksums line still matches the altered
            # file only if SHA256SUMS is rewritten too -- do that, as a forger
            # would, and the signature is what still fails.
            manifest_path = os.path.join(root, "manifest.json")
            with open(manifest_path, "rb") as fh:
                forged = fh.read().replace(b"SOC 2 fieldwork", b"SOC 2 fieldwerk")
            with open(manifest_path, "wb") as fh:
                fh.write(forged)
            import hashlib
            sums = os.path.join(root, "SHA256SUMS")
            lines = []
            for line in open(sums, encoding="utf-8"):
                digest, _, name = line.rstrip("\n").partition("  ")
                if name == "manifest.json":
                    digest = hashlib.sha256(forged).hexdigest()
                lines.append(f"{digest}  {name}\n")
            open(sums, "w", encoding="utf-8").write("".join(lines))
            open(os.path.join(root, "MANIFEST.sha256"), "w", encoding="utf-8").write(
                f"{hashlib.sha256(forged).hexdigest()}  manifest.json\n")
            out = StringIO()
            with contextlib.redirect_stdout(out):
                code = verifier.main(root)
            self.assertEqual(code, 1)
            self.assertIn("SIGNATURE DOES NOT VERIFY", out.getvalue())

    def test_rotation_keeps_old_packages_verifying_and_signs_new_ones_with_the_new_key(self):
        self.seal()
        old_id = self.package.signing_key_id
        out = StringIO()
        call_command("rotate_signing_key", "--label", "FY27", stdout=out)
        self.assertIn("Retired", out.getvalue())
        self.assertIn("New key", out.getvalue())
        keys = {k.key_id: k for k in SigningKey.objects.all()}
        self.assertIsNotNone(keys[old_id].retired_at)
        new_id = [k for k in keys if k != old_id][0]
        self.assertEqual(keys[new_id].label, "FY27")
        self.assertIsNone(keys[new_id].retired_at)
        # The old package still verifies under the key it carries.
        self.package.refresh_from_db()
        self.assertEqual(signing.signature_status(self.package), "valid")
        # A new package is signed with the new key.
        other = EvidencePackage.objects.create(name="Next", created_by=self.manager,
                                               created_by_name="Mia")
        self.manager_client.post(f"/api/evidence-packages/{other.pk}/add_controls/",
                                 {"controls": [self.tree.c2.pk]}, format="json")
        r = self.manager_client.post(f"/api/evidence-packages/{other.pk}/seal/",
                                     {"assertion": ASSERTION}, format="json")
        self.assertEqual(r.data["signing_key_id"], new_id)
        listed = APIClient().get("/api/signing-keys/").data
        self.assertEqual(listed["current"]["key_id"], new_id)
        self.assertEqual({k["key_id"]: k["current"] for k in listed["keys"]}, {old_id: False, new_id: True})
        show = StringIO()
        call_command("rotate_signing_key", "--show", stdout=show)
        self.assertIn(new_id, show.getvalue())

    def test_health_publishes_the_key(self):
        body = APIClient().get("/api/health/").data["signing"]
        self.assertTrue(body["enabled"])
        self.assertEqual(len(body["key_id"]), 16)
        self.assertEqual(body["fingerprint"][:16], body["key_id"])

    def test_a_key_from_the_environment_is_used_as_is(self):
        from cryptography.hazmat.primitives.asymmetric import ed25519
        seed = os.urandom(32)
        expected = signing.key_id(ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key())
        with override_settings(SIGNING_KEY=base64.b64encode(seed).decode()):
            self.seal()
        self.assertEqual(self.package.signing_key_id, expected)
        with override_settings(SIGNING_KEY="not a key"):
            from django.core.exceptions import ImproperlyConfigured
            with self.assertRaises(ImproperlyConfigured):
                signing.load_private_key()


class UnsignedTests(PackageTestBase):
    @override_settings(SIGNING_ENABLED=False)
    def test_without_a_key_packages_seal_unsigned_and_everything_still_works(self):
        self.add_control()
        r = self.seal()
        self.assertEqual(r.data["manifest_signature"], "")
        self.assertEqual(self.manager_client.get(
            f"/api/evidence-packages/{self.package.pk}/signature/").data["signed"], False)
        v = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/verify/").data
        self.assertEqual((v["ok"], v["signature"]), (True, "unsigned"))
        self.issue_to(self.auditor)
        r = self.client_for(self.auditor).get(f"/api/evidence-packages/{self.package.pk}/export/")
        zf = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
        self.assertNotIn("manifest.sig", zf.namelist())
        self.assertIn("carries no", zf.read("README.txt").decode())
        self.assertEqual(APIClient().get("/api/health/").data["signing"]["enabled"], False)
        self.assertIsNone(APIClient().get("/api/signing-keys/").data["current"])
