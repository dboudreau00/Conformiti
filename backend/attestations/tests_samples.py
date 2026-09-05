"""
Sample rows: the operating-effectiveness workpaper. Who may list items and
when, who records results, what the seal freezes, and what the bundle says.
"""
import io
import json
import zipfile

from attestations.models import PackageEvidence, PackageSample
from attestations.tests import PackageTestBase
from testutils import make_doc


class SampleTests(PackageTestBase):
    def setUp(self):
        super().setUp()
        self.add_control()
        self.row = self.package.controls.get()
        self.artefact = PackageEvidence.objects.get(package_control=self.row)
        self.owner_client = self.client_for(self.owner)
        self.auditor_client = self.client_for(self.auditor)

    def list_item(self, client=None, **extra):
        body = {"package_control": self.row.pk, "identifier": "u-1042",
                "description": "Leaver removed within a day", "population_ref": "row 7",
                "evidence": self.artefact.pk}
        body.update(extra)
        return (client or self.manager_client).post("/api/package-samples/", body, format="json")

    # ------------------------------------------------------------- draft
    def test_the_organisation_lists_items_and_the_population_while_drafting(self):
        r = self.manager_client.patch(f"/api/package-controls/{self.row.pk}/", {
            "population_size": 42, "population_source": "HR termination report",
            "sampling_method": "random"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["sampling_method_display"], "Random")
        r = self.list_item()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["evidence_name"], "Access Control Policy")
        self.assertEqual(r.data["selected_by_name"], self.manager.get_full_name())
        self.assertEqual(r.data["result"], "pending")
        self.assertFalse(r.data["sealed_in"])
        rows = self.manager_client.get(f"/api/package-controls/?package={self.package.pk}").data["results"]
        self.assertEqual(rows[0]["sample_summary"], {"total": 1, "pass": 0, "fail": 0, "not_tested": 0, "pending": 1})
        self.assertEqual(rows[0]["samples"][0]["identifier"], "u-1042")

    def test_only_the_frameworks_capability_lists_items_in_a_draft(self):
        self.assertEqual(self.list_item(self.owner_client).status_code, 403)
        self.assertEqual(self.list_item(self.client_for(self.viewer)).status_code, 403)
        r = self.owner_client.patch(f"/api/package-controls/{self.row.pk}/", {"population_size": 3}, format="json")
        self.assertEqual(r.status_code, 404)   # the draft is not even readable to them

    def test_evidence_must_be_pinned_to_the_same_control(self):
        self.add_control(self.tree.c2)
        other = self.package.controls.get(control=self.tree.c2)
        r = self.manager_client.post("/api/package-samples/", {
            "package_control": other.pk, "identifier": "x", "evidence": self.artefact.pk}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("evidence", r.data)

    def test_results_cannot_be_recorded_before_sealing(self):
        r = self.list_item(result="pass")
        self.assertEqual(r.status_code, 400)
        self.assertIn("result", r.data)
        self.list_item()
        sample = PackageSample.objects.get()
        r = self.manager_client.patch(f"/api/package-samples/{sample.pk}/", {"result": "pass"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_identifiers_are_unique_per_control(self):
        self.assertEqual(self.list_item().status_code, 201)
        r = self.list_item()
        self.assertEqual(r.status_code, 400)

    # -------------------------------------------------------------- seal
    def test_sealing_freezes_the_listed_items_into_the_manifest(self):
        self.manager_client.patch(f"/api/package-controls/{self.row.pk}/", {
            "population_size": 42, "population_source": "HR report", "sampling_method": "random"}, format="json")
        self.list_item()
        self.list_item(identifier="u-1077", population_ref="row 19")
        self.seal()
        manifest = json.loads(self.package.manifest_json)
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(manifest["totals"]["samples"], 2)
        control = manifest["controls"][0]
        self.assertEqual(control["population"], {"size": 42, "source": "HR report", "sampling_method": "random"})
        self.assertEqual([s["identifier"] for s in control["samples"]], ["u-1042", "u-1077"])
        self.assertEqual(control["samples"][0]["evidence_path"], control["evidence"][0]["path"])
        self.assertEqual(control["samples"][0]["result"], "pending")
        self.assertTrue(all(s.sealed_in for s in PackageSample.objects.all()))
        # Nothing the organisation does afterwards changes the sealed items.
        sample = PackageSample.objects.first()
        r = self.manager_client.patch(f"/api/package-samples/{sample.pk}/", {"identifier": "changed"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.manager_client.delete(f"/api/package-samples/{sample.pk}/")
        self.assertEqual(r.status_code, 403)
        r = self.list_item(identifier="late")
        self.assertEqual(r.status_code, 403)
        r = self.manager_client.patch(f"/api/package-controls/{self.row.pk}/", {"population_size": 1}, format="json")
        self.assertEqual(r.status_code, 400)

    # ----------------------------------------------------------- auditor
    def _issued(self):
        self.list_item()
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        return PackageSample.objects.get()

    def test_the_issued_auditor_records_results_and_an_exception_needs_a_note(self):
        sample = self._issued()
        r = self.auditor_client.patch(f"/api/package-samples/{sample.pk}/", {"result": "fail"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("exception_note", r.data)
        r = self.auditor_client.patch(f"/api/package-samples/{sample.pk}/", {
            "result": "fail", "exception_note": "Removed 4 days late."}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["tested_by_name"], self.auditor.get_full_name())
        self.assertIsNotNone(r.data["tested_at"])
        # A sealed item's identity stays fixed even for the auditor...
        r = self.auditor_client.patch(f"/api/package-samples/{sample.pk}/", {"identifier": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        # ...and the organisation never touches a result.
        r = self.manager_client.patch(f"/api/package-samples/{sample.pk}/", {"result": "pass"}, format="json")
        self.assertEqual(r.status_code, 403)
        rows = self.auditor_client.get(f"/api/package-controls/?package={self.package.pk}").data["results"]
        self.assertEqual(rows[0]["sample_summary"]["fail"], 1)

    def test_the_auditor_adds_their_own_selections_after_sealing(self):
        self._issued()
        r = self.auditor_client.post("/api/package-samples/", {
            "package_control": self.row.pk, "identifier": "u-9001", "population_ref": "row 40",
            "evidence": self.artefact.pk, "result": "pass"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["sealed_in"])
        self.assertEqual(r.data["tested_by_name"], self.auditor.get_full_name())
        # Their own rows they may correct or drop; the manifest's they may not.
        r = self.auditor_client.patch(f"/api/package-samples/{r.data['id']}/", {"description": "leaver"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.auditor_client.delete(f"/api/package-samples/{r.data['id']}/").status_code, 204)
        sealed = PackageSample.objects.get(sealed_in=True)
        self.assertEqual(self.auditor_client.delete(f"/api/package-samples/{sealed.pk}/").status_code, 403)
        # And the sampling note is theirs, like a conclusion.
        r = self.auditor_client.patch(f"/api/package-controls/{self.row.pk}/", {
            "sampling_note": "25 of 42 at random"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.manager_client.patch(f"/api/package-controls/{self.row.pk}/", {"sampling_note": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_an_auditor_without_a_grant_sees_nothing(self):
        self.list_item()
        self.seal()
        self.assertEqual(self.auditor_client.get("/api/package-samples/").data["count"], 0)
        sample = PackageSample.objects.get()
        r = self.auditor_client.patch(f"/api/package-samples/{sample.pk}/", {"result": "pass"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_withdrawal_closes_the_workpaper(self):
        sample = self._issued()
        self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/withdraw/", {"reason": "done"}, format="json")
        r = self.auditor_client.patch(f"/api/package-samples/{sample.pk}/", {"result": "pass"}, format="json")
        self.assertIn(r.status_code, (400, 404))

    # ------------------------------------------------------------ bundle
    def test_the_bundle_carries_the_sample_workpaper(self):
        sample = self._issued()
        self.auditor_client.patch(f"/api/package-samples/{sample.pk}/", {
            "result": "fail", "exception_note": "Late removal"}, format="json")
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
        names = zf.namelist()
        self.assertIn("samples.csv", names)
        samples = zf.read("samples.csv").decode("utf-8-sig")
        self.assertIn("u-1042", samples)
        self.assertIn("Exception", samples)
        self.assertIn("Late removal", samples)
        self.assertIn("yes", samples)   # in sealed manifest
        controls = zf.read("controls.csv").decode("utf-8-sig")
        self.assertIn("Sample exceptions", controls.splitlines()[0])
        sums = zf.read("SHA256SUMS").decode("utf-8")
        self.assertIn("samples.csv", sums)
        readme = zf.read("README.txt").decode("utf-8")
        self.assertIn("Sample items     1 (1 exception(s))", readme)

    def test_a_document_pinned_elsewhere_is_not_a_valid_sample_artefact(self):
        other_doc = make_doc(self.tree.ctrl2, owner=self.owner, name="Other")
        self.add_control(self.tree.c2)
        other_row = self.package.controls.get(control=self.tree.c2)
        r = self.manager_client.post("/api/package-evidence/", {
            "package_control": other_row.pk, "document": other_doc.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.list_item(evidence=r.data["id"])
        self.assertEqual(r.status_code, 400)
