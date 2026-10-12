"""A write that arrives after a seal must be refused, and the seal must survive.

On PostgreSQL the guard is a row lock; SQLite ignores row locks, so each test
makes the loss deterministic another way: the view is handed an instance that
was read BEFORE the seal committed (what a request that started earlier holds).
Before the locks, the view believed that stale copy was still a draft and wrote
it back over the sealed row: an empty manifest, digest and signature under a
"sealed" audit entry, or a sealed package deleted outright.
"""
from unittest import mock

from attestations import views
from attestations.models import EvidencePackage, PackageControl, PackageEvidence
from attestations.tests import PackageTestBase


class StaleWriteTests(PackageTestBase):
    def assert_still_sealed(self):
        self.package.refresh_from_db()
        self.assertEqual(self.package.status, EvidencePackage.Status.SEALED)
        self.assertTrue(self.package.manifest_sha256)
        self.assertTrue(self.package.manifest_json)

    def test_a_package_save_from_before_the_seal_is_refused(self):
        self.add_control()
        stale = EvidencePackage.objects.get(pk=self.package.pk)
        self.seal()
        with mock.patch.object(views.EvidencePackageViewSet, "get_object", return_value=stale):
            r = self.manager_client.patch(f"/api/evidence-packages/{self.package.pk}/",
                                          {"name": "Edited after the fact"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assert_still_sealed()
        self.assertNotEqual(self.package.name, "Edited after the fact")

    def test_deleting_a_package_read_before_the_seal_is_refused(self):
        self.add_control()
        stale = EvidencePackage.objects.get(pk=self.package.pk)
        self.seal()
        with mock.patch.object(views.EvidencePackageViewSet, "get_object", return_value=stale):
            r = self.manager_client.delete(f"/api/evidence-packages/{self.package.pk}/")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertTrue(EvidencePackage.objects.filter(pk=self.package.pk).exists())
        self.assert_still_sealed()

    def test_a_snapshot_field_sent_after_the_seal_is_refused(self):
        self.add_control()
        stale = PackageControl.objects.select_related("package").get(package=self.package)
        self.seal()
        with mock.patch.object(views.PackageControlViewSet, "get_object", return_value=stale):
            r = self.manager_client.patch(f"/api/package-controls/{stale.pk}/",
                                          {"note": "added after sealing"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(PackageControl.objects.get(pk=stale.pk).note, "")
        self.assert_still_sealed()

    def test_a_pinned_evidence_row_edited_after_the_seal_is_refused(self):
        self.add_control()
        stale = PackageEvidence.objects.select_related("package_control__package").get(
            package_control__package=self.package)
        self.seal()
        with mock.patch.object(views.PackageEvidenceViewSet, "get_object", return_value=stale):
            r = self.manager_client.patch(f"/api/package-evidence/{stale.pk}/",
                                          {"evidence_note": "changed after sealing"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertNotEqual(PackageEvidence.objects.get(pk=stale.pk).evidence_note, "changed after sealing")
        self.assert_still_sealed()

    def test_a_withdrawal_keeps_the_manifest_the_seal_wrote(self):
        """withdraw read the row before the seal finished and saved that copy
        whole: a withdrawn package with an empty manifest, digest and signature."""
        self.add_control()
        stale = EvidencePackage.objects.get(pk=self.package.pk)      # read while it was a draft
        self.seal()
        sealed = (self.package.manifest_sha256, self.package.manifest_json, self.package.manifest_signature)
        self.assertTrue(sealed[0] and sealed[1])
        with mock.patch.object(views.EvidencePackageViewSet, "get_object", return_value=stale):
            r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/withdraw/",
                                         {"reason": "test"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.package.refresh_from_db()
        self.assertEqual(self.package.status, EvidencePackage.Status.WITHDRAWN)
        self.assertEqual((self.package.manifest_sha256, self.package.manifest_json,
                          self.package.manifest_signature), sealed)
