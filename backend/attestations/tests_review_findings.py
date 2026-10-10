"""Roll-forward pairing of pinned evidence, the signing-key registry keyed by
the whole public key, and a blank key file."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings

from attestations import rollforward, signing
from attestations.models import SigningKey


def row(name, sha, doc=None):
    return SimpleNamespace(document_id=doc, document_name=name, content_sha256=sha)


def package(*rows):
    return SimpleNamespace(evidence=SimpleNamespace(all=lambda: list(rows)))


class EvidencePairingTests(SimpleTestCase):
    def diff(self, now, before):
        added, removed, changed, same = rollforward._evidence_diff(package(*now), package(*before))
        return len(added), len(removed), len(changed), len(same)

    def test_two_rows_with_one_name_and_no_live_document_stay_two(self):
        before = [row("Access list", "a"), row("Access list", "b")]
        now = [row("Access list", "a"), row("Access list", "b")]
        self.assertEqual(self.diff(now, before), (0, 0, 0, 2))

    def test_a_row_that_gained_a_twin_is_added_not_lost(self):
        before = [row("Access list", "a")]
        now = [row("Access list", "a"), row("Access list", "c")]
        self.assertEqual(self.diff(now, before), (1, 0, 0, 1))

    def test_a_changed_document_is_still_a_change(self):
        before = [row("Policy", "old")]
        now = [row("Policy", "new")]
        self.assertEqual(self.diff(now, before), (0, 0, 1, 0))

    def test_identical_content_pairs_before_the_leftovers_do(self):
        before = [row("Log", "x"), row("Log", "y")]
        now = [row("Log", "y"), row("Log", "z")]
        # y matches y; z is what x became.
        self.assertEqual(self.diff(now, before), (0, 0, 1, 1))

    def test_a_vanished_and_a_new_artefact(self):
        before = [row("Old report", "a")]
        now = [row("New report", "b")]
        self.assertEqual(self.diff(now, before), (1, 1, 0, 0))

    def test_a_live_document_is_matched_by_id_whatever_it_is_called(self):
        before = [row("Policy v1", "a", doc=7)]
        now = [row("Policy v2", "b", doc=7)]
        self.assertEqual(self.diff(now, before), (0, 0, 1, 0))


class BlankKeyFileTests(SimpleTestCase):
    def setUp(self):
        signing._cache.update(path=None, mtime=None, key=None)
        self.addCleanup(lambda: signing._cache.update(path=None, mtime=None, key=None))

    def test_an_empty_key_file_is_a_misconfiguration_not_signing_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signing.pem"
            path.write_text("  \n", encoding="utf-8")
            with override_settings(SIGNING_ENABLED=True, SIGNING_KEY="", SIGNING_KEY_FILE=str(path)):
                with self.assertRaises(ImproperlyConfigured) as caught:
                    signing.load_private_key()
                self.assertIn("empty", str(caught.exception))
                # The health and settings views report it instead of crashing.
                info = signing.current_key_info()
                self.assertIsNone(info["key_id"])
                self.assertIn("empty", info["error"])

    def test_a_missing_file_is_still_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signing.pem"
            with override_settings(SIGNING_ENABLED=True, SIGNING_KEY="", SIGNING_KEY_FILE=str(path)):
                self.assertIsNotNone(signing.load_private_key())
            self.assertTrue(path.read_text(encoding="utf-8").strip())

    def test_signing_switched_off_is_still_none(self):
        with override_settings(SIGNING_ENABLED=False, SIGNING_KEY="", SIGNING_KEY_FILE="/nowhere"):
            self.assertIsNone(signing.load_private_key())


class KeyRegistryTests(TestCase):
    """A registry row is the whole public key; the 16-character id is a label."""

    def fresh(self):
        return signing.public_b64(signing.ed25519.Ed25519PrivateKey.generate().public_key())

    def test_a_key_registers_once_and_is_found_by_its_whole_key(self):
        pub = self.fresh()
        first = signing.register_key(pub)
        again = signing.register_key(pub)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(first.key_id, signing.key_id(pub))
        self.assertEqual(SigningKey.objects.filter(public_key=pub).count(), 1)

    def test_a_different_key_with_the_same_short_id_is_refused_not_reused(self):
        pub = self.fresh()
        signing.register_key(pub)
        other = self.fresh()
        with transaction.atomic():
            SigningKey.objects.filter(public_key=pub).update(key_id=signing.key_id(other))
        with self.assertRaises(ImproperlyConfigured), transaction.atomic():
            signing.register_key(other)
        # The first key's row was not rewritten to the second key.
        self.assertEqual(SigningKey.objects.get(public_key=pub).public_key, pub)

    def test_registering_a_new_key_retires_the_old_one(self):
        old, new = self.fresh(), self.fresh()
        signing.register_key(old)
        signing.register_key(new)
        self.assertIsNotNone(SigningKey.objects.get(public_key=old).retired_at)
        self.assertIsNone(SigningKey.objects.get(public_key=new).retired_at)


from attestations import bundle  # noqa: E402
from attestations.models import PackageEvidence  # noqa: E402
from attestations.tests import PackageTestBase  # noqa: E402


class BundleFindingsTests(PackageTestBase):
    """What an exported bundle says about itself when it is cut short or incomplete."""

    def export_zip(self):
        import io
        import zipfile

        self.add_control()
        self.seal()
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        return zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))

    def audit_two_documents_events(self):
        from audit.models import AuditLog

        doc_ids = list(PackageEvidence.objects.filter(
            package_control__package=self.package, document__isnull=False
        ).values_list("document_id", flat=True))
        self.assertTrue(doc_ids, "the fixture pins no live document")
        for n in range(3):
            AuditLog.objects.create(action="update", object_type="documents",
                                    object_id=str(doc_ids[0]), detail=f"event {n}")

    def test_a_trail_that_fits_is_whole_and_says_nothing_about_a_cut(self):
        self.add_control()
        self.audit_two_documents_events()
        self.seal()
        rows, total = bundle.trail_rows(self.package)
        self.assertEqual(len(rows), total)
        zf = self.export_zip_again()
        self.assertNotIn("trail.csv holds the first", zf.read("README.txt").decode("utf-8"))

    def export_zip_again(self):
        import io
        import zipfile

        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        return zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))

    def test_a_trail_that_is_cut_says_so_in_the_readme(self):
        from unittest import mock

        self.add_control()
        self.audit_two_documents_events()
        self.seal()
        with mock.patch.object(bundle, "TRAIL_LIMIT", 2):
            rows, total = bundle.trail_rows(self.package)
            self.assertEqual((len(rows), total >= 3), (2, True))
            zf = self.export_zip_again()
        readme = zf.read("README.txt").decode("utf-8")
        self.assertIn(f"trail.csv holds the first 2 of {total} entries, oldest first", readme)
        self.assertEqual(len(zf.read("trail.csv").decode("utf-8-sig").splitlines()) - 1, 2)

    def test_the_trail_is_oldest_first(self):
        self.add_control()
        self.audit_two_documents_events()
        self.seal()
        rows, _ = bundle.trail_rows(self.package)
        stamps = [r[0] for r in rows]
        self.assertEqual(stamps, sorted(stamps))

    def test_a_bundle_that_cannot_read_its_verifier_fails_instead_of_leaving_it_out(self):
        import io
        from pathlib import Path
        from unittest import mock

        self.add_control()
        self.seal()
        with mock.patch.object(bundle, "VERIFIER", Path("/nonexistent/verify.py")):
            with self.assertRaises(OSError):
                bundle.write_bundle(self.package, io.BytesIO())
