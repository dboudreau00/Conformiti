"""The in-app signature check against the published key list, and the seal's row lock."""
from accounts import tenancy
from accounts.models import Workspace

from . import signing
from .models import EvidencePackage, SigningKey
from .tests import PackageTestBase


class SignatureStatusTests(PackageTestBase):
    """The in-app check trusts the published key list, never the public key stored beside the signature."""

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.package.refresh_from_db()

    def test_a_sealed_package_verifies(self):
        self.assertEqual(signing.signature_status(self.package), "valid")

    def test_a_manifest_re_signed_with_an_unpublished_key_is_not_valid(self):
        import json

        from cryptography.hazmat.primitives.asymmetric import ed25519

        forged = ed25519.Ed25519PrivateKey.generate()
        manifest = json.loads(self.package.manifest_json)
        manifest["package"]["name"] = "Rewritten after the fact"
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")

        public = forged.public_key()
        self.package.manifest_json = raw.decode("utf-8")
        self.package.manifest_signature = signing.base64.b64encode(forged.sign(raw)).decode("ascii")
        self.package.signing_public_key = signing.public_b64(public)
        self.package.signing_key_id = signing.key_id(public)
        self.package.save()

        # Self-consistent, and refused: no such key was ever published.
        self.assertTrue(signing.verify_bytes(raw, self.package.manifest_signature,
                                             self.package.signing_public_key))
        self.assertEqual(signing.signature_status(self.package), "invalid")

    def test_a_swapped_public_key_on_a_published_key_id_is_not_valid(self):
        from cryptography.hazmat.primitives.asymmetric import ed25519

        other = ed25519.Ed25519PrivateKey.generate().public_key()
        self.package.signing_public_key = signing.public_b64(other)
        self.package.save(update_fields=["signing_public_key"])
        self.assertEqual(signing.signature_status(self.package), "invalid")

    def test_another_organisations_key_is_not_valid_here(self):
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-sig")
        with tenancy.scoped(beta):
            theirs = signing.current_key_info(create=True)
            signing.register_key(theirs["public_key"])
        row = SigningKey.objects.get(key_id=theirs["key_id"])
        self.assertEqual(row.workspace_id, beta.pk)

        self.package.signing_key_id = theirs["key_id"]
        self.package.signing_public_key = theirs["public_key"]
        self.package.save(update_fields=["signing_key_id", "signing_public_key"])
        self.assertEqual(signing.signature_status(self.package), "invalid")

    def test_an_unsigned_package_says_so(self):
        self.package.manifest_signature = ""
        self.package.save(update_fields=["manifest_signature"])
        self.assertEqual(signing.signature_status(self.package), "unsigned")


class SealLockTests(PackageTestBase):
    """Sealing re-reads the package under a row lock, so evidence pinned in the gap cannot land outside the manifest."""

    def test_a_package_sealed_in_the_gap_is_caught(self):
        """Stands in for the race: the view's copy says draft, the database says sealed."""
        self.add_control()
        stale = EvidencePackage.objects.get(pk=self.package.pk)
        self.assertTrue(stale.is_open)
        EvidencePackage.objects.filter(pk=self.package.pk).update(
            status=EvidencePackage.Status.SEALED)

        r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/seal/",
                                     {"assertion": "A" * 80}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("read-only", str(r.data))

    def test_pinning_after_the_seal_is_refused(self):
        self.add_control()
        self.seal()
        row = self.package.controls.first()
        r = self.manager_client.post("/api/package-evidence/", {
            "package_control": row.pk, "document": self.doc.pk}, format="json")
        self.assertIn(r.status_code, (400, 403), r.data)

    def test_unpinning_after_the_seal_is_refused(self):
        self.add_control()
        row = self.package.controls.first()
        pinned = row.evidence.first()
        self.assertIsNotNone(pinned)
        self.seal()
        r = self.manager_client.delete(f"/api/package-evidence/{pinned.pk}/")
        self.assertIn(r.status_code, (400, 403), r.status_code)
        self.assertTrue(row.evidence.filter(pk=pinned.pk).exists())

    def test_sealing_still_works(self):
        self.add_control()
        r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/seal/",
                                     {"assertion": "A" * 80}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.package.refresh_from_db()
        self.assertEqual(self.package.status, EvidencePackage.Status.SEALED)
        self.assertTrue(self.package.manifest_sha256)
