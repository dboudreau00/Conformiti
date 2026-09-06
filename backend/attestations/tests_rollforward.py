"""Roll-forward: next year's draft from last year's sealed package, and the
year-over-year diff computed from the two packages' own snapshots."""
import json

from django.core.files.uploadedfile import SimpleUploadedFile

from attestations.models import EvidencePackage, PackageControl
from attestations.tests import ASSERTION, PackageTestBase
from compliance.models import ControlEvidence
from testutils import make_doc


class RollForwardTests(PackageTestBase):
    def setUp(self):
        super().setUp()
        self.add_control()
        self.add_control(self.tree.c2)
        # An exception noted last year on the first control.
        row = PackageControl.objects.get(package=self.package, control=self.tree.c1)
        row.design_conclusion = PackageControl.Conclusion.EXCEPTIONS
        row.auditor_note = "Two leavers kept access for a week."
        row.save()
        self.seal()

    def roll(self, **body):
        return self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/roll_forward/",
                                        body, format="json")

    def test_rolling_forward_opens_a_draft_with_todays_evidence_and_the_link_back(self):
        # Since sealing, the policy got a new version and a second document
        # was linked to the first control.
        self.doc.file.save("v2.txt", SimpleUploadedFile("v2.txt", b"policy v2"), save=True)
        self.doc.version = 2
        self.doc.save()
        extra = make_doc(self.tree.ctrl1, owner=self.owner, name="Access review Q4", content=b"review")
        ControlEvidence.objects.create(control=self.tree.c1, document=extra, linked_by=self.manager)

        r = self.roll(name="SOC 2 fieldwork FY27")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "draft")
        self.assertEqual(r.data["prior_package"], self.package.pk)
        self.assertEqual(r.data["prior_package_name"], "SOC 2 fieldwork")
        self.assertEqual(r.data["control_count"], 2)
        self.assertEqual(r.data["skipped"], [])
        new = EvidencePackage.objects.get(pk=r.data["id"])
        self.assertEqual((new.engagement, new.audit_firm, new.assurance_type),
                         (self.package.engagement, self.package.audit_firm, self.package.assurance_type))
        first = new.controls.get(control=self.tree.c1)
        # Conclusions belong to last year; the new row starts clean.
        self.assertEqual(first.design_conclusion, "pending")
        self.assertEqual(sorted(e.document_name for e in first.evidence.all()),
                         ["Access Control Policy", "Access review Q4"])
        self.assertEqual(first.evidence.get(document=self.doc).pinned_version, 2)
        # The predecessor lists its successor.
        me = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/").data
        self.assertEqual(me["successors"][0]["id"], new.pk)

    def test_the_diff_reads_from_snapshots(self):
        self.doc.file.save("v2.txt", SimpleUploadedFile("v2.txt", b"policy v2"), save=True)
        new_id = self.roll().data["id"]
        # Drop the second control this year; add nothing.
        PackageControl.objects.get(package_id=new_id, control=self.tree.c2).delete()
        d = self.manager_client.get(f"/api/evidence-packages/{new_id}/diff/").data
        self.assertEqual(d["prior"]["id"], self.package.pk)
        self.assertEqual(d["prior"]["manifest_sha256"], self.package.manifest_sha256)
        self.assertEqual(d["totals"]["controls_removed"], 1)
        self.assertEqual(d["controls"]["removed"][0]["control_ref"], "TC1.2")
        kept = d["controls"]["kept"][0]
        self.assertEqual(kept["control_ref"], "TC1.1")
        self.assertTrue(kept["prior_exception"])
        self.assertEqual(kept["prior_auditor_note"], "Two leavers kept access for a week.")
        self.assertEqual(len(kept["evidence"]["changed"]), 1)     # the policy's bytes changed
        self.assertEqual(d["totals"]["prior_exceptions_open"], 1)
        # A package with no predecessor says so.
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/diff/")
        self.assertEqual(r.status_code, 400)

    def test_the_sealed_manifest_names_its_predecessor(self):
        new_id = self.roll().data["id"]
        r = self.manager_client.post(f"/api/evidence-packages/{new_id}/seal/",
                                     {"assertion": ASSERTION}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        manifest = json.loads(EvidencePackage.objects.get(pk=new_id).manifest_json)
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["package"]["prior"]["id"], self.package.pk)
        self.assertEqual(manifest["package"]["prior"]["manifest_sha256"], self.package.manifest_sha256)
        # Last year's manifest has no such key and is untouched.
        self.assertNotIn("prior", json.loads(self.package.manifest_json)["package"])

    def test_predecessor_rules(self):
        # Only the frameworks capability rolls forward; a draft cannot be rolled from.
        self.assertEqual(self.client_for(self.viewer).post(
            f"/api/evidence-packages/{self.package.pk}/roll_forward/").status_code, 403)
        draft = EvidencePackage.objects.create(name="Draft", created_by=self.manager)
        self.assertEqual(self.manager_client.post(
            f"/api/evidence-packages/{draft.pk}/roll_forward/").status_code, 400)
        # prior_package is settable on a draft, must be sealed, and cannot loop.
        r = self.manager_client.patch(f"/api/evidence-packages/{draft.pk}/",
                                      {"prior_package": self.package.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        other = EvidencePackage.objects.create(name="Other draft", created_by=self.manager)
        self.assertEqual(self.manager_client.patch(f"/api/evidence-packages/{draft.pk}/",
                                                   {"prior_package": other.pk}, format="json").status_code, 400)
        self.assertEqual(self.manager_client.patch(f"/api/evidence-packages/{draft.pk}/",
                                                   {"prior_package": draft.pk}, format="json").status_code, 400)
        # The auditor cannot read a draft's diff against a package they were not issued.
        self.assertEqual(self.client_for(self.auditor).get(
            f"/api/evidence-packages/{draft.pk}/diff/").status_code, 404)
