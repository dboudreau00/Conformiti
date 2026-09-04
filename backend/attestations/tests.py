"""
Evidence packages: the disclosure boundary, the seal, and the bundle.

The tests that matter most are the RBAC ones. This app contains the only place
in Conformiti where folder permissions are bypassed, so both directions have to
be pinned: an auditor CAN read exactly what was packaged for them, and CANNOT
read anything else — including the same document through any other route.
"""
import io
import json
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from accounts.models import Role
from attestations import manifest as mf
from attestations.models import (
    EvidencePackage,
    PackageControl,
    PackageEvidence,
    PackageGrant,
)
from audit.models import AuditLog
from compliance.models import ControlEvidence
from documents.access import accessible_folder_ids
from documents.models import EDIT, VIEW
from testutils import APITestBase, grant, make_doc, make_user

ASSERTION = (
    "Management asserts that the controls described in this package were in place "
    "throughout the period stated, and that the evidence attached is complete and "
    "accurate to the best of our knowledge."
)


class PackageTestBase(APITestBase):
    """A manager with a draft package holding one control and one document."""

    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, owner=self.owner,
                            name="Access Control Policy", content=b"policy bytes")
        self.link = ControlEvidence.objects.create(
            control=self.tree.c1, document=self.doc, linked_by=self.manager,
            note="Signed policy",
        )
        self.manager_client = self.client_for(self.manager)
        self.package = EvidencePackage.objects.create(
            name="SOC 2 fieldwork", engagement="FY26 Type II",
            audit_firm="Example Assurance LLP",
            framework=self.tree.framework,
            assurance_type=EvidencePackage.Assurance.TYPE_II,
            created_by=self.manager,
            created_by_name=self.manager.get_full_name(),
        )

    def add_control(self, control=None):
        r = self.manager_client.post(
            f"/api/evidence-packages/{self.package.pk}/add_controls/",
            {"controls": [(control or self.tree.c1).pk]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def seal(self):
        r = self.manager_client.post(
            f"/api/evidence-packages/{self.package.pk}/seal/",
            {"assertion": ASSERTION}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.package.refresh_from_db()
        return r

    def issue_to(self, user, days=30):
        r = self.manager_client.post("/api/package-grants/", {
            "package": self.package.pk, "user": user.pk,
            "expires_at": (timezone.now() + timezone.timedelta(days=days)).isoformat(),
        }, format="json")
        return r


# --------------------------------------------------------------------------- #
# Assembling and sealing
# --------------------------------------------------------------------------- #
class AssembleTests(PackageTestBase):
    def test_adding_a_control_snapshots_it_with_its_linked_evidence(self):
        self.add_control()
        row = PackageControl.objects.get(package=self.package)
        self.assertEqual(row.control_ref, "TC1.1")
        self.assertEqual(row.framework_name, "Test Framework")
        self.assertEqual(row.mgmt_status_display, "Not started")
        item = PackageEvidence.objects.get(package_control=row)
        self.assertEqual(item.document_name, "Access Control Policy")
        self.assertEqual(item.size_bytes, len(b"policy bytes"))
        self.assertEqual(item.content_sha256, mf.sha256_hex(b"policy bytes"))
        # The link's own provenance is carried forward: who said this evidences
        # this control, and when.
        self.assertEqual(item.linked_by_name, self.manager.get_full_name())
        self.assertIsNotNone(item.evidence_linked_at)

    def test_the_snapshot_does_not_follow_later_edits(self):
        self.add_control()
        self.tree.c1.title = "Renamed after packaging"
        self.tree.c1.save()
        self.doc.name = "Renamed document"
        self.doc.save()
        row = PackageControl.objects.get(package=self.package)
        self.assertEqual(row.title, "First control")
        self.assertEqual(row.evidence.get().document_name, "Access Control Policy")

    def test_a_control_with_no_evidence_still_gets_a_row(self):
        r = self.manager_client.post(
            f"/api/evidence-packages/{self.package.pk}/add_controls/",
            {"controls": [self.tree.c2.pk]}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(PackageControl.objects.filter(control=self.tree.c2).exists())

    def test_sealing_requires_an_assertion_and_at_least_one_control(self):
        r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/seal/",
                                     {"assertion": ASSERTION}, format="json")
        self.assertEqual(r.status_code, 400)
        self.add_control()
        r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/seal/",
                                     {"assertion": "too short"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("assertion", r.data)

    def test_sealing_refuses_when_a_pinned_file_has_changed(self):
        """The package must never claim bytes it can no longer produce."""
        self.add_control()
        self.doc.file.save("changed.txt", SimpleUploadedFile("changed.txt", b"different"), save=True)
        r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/seal/",
                                     {"assertion": ASSERTION}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(r.data["drifted"]), 1)
        self.assertEqual(r.data["drifted"][0]["document"], "Access Control Policy")

    def test_sealing_stamps_a_digest_and_records_it_in_the_trail(self):
        self.add_control()
        self.seal()
        self.assertEqual(self.package.status, "sealed")
        self.assertEqual(len(self.package.manifest_sha256), 64)
        self.assertEqual(self.package.sealed_by_name, self.manager.get_full_name())
        entry = AuditLog.objects.filter(action="seal").latest("timestamp")
        # Digest first: detail is capped at 255 characters and the digest is the
        # only thing in the row that binds it to these bytes.
        self.assertTrue(entry.detail.startswith(f"sha256={self.package.manifest_sha256}"))

    def test_a_sealed_package_is_read_only(self):
        self.add_control()
        self.seal()
        url = f"/api/evidence-packages/{self.package.pk}/"
        self.assertEqual(self.manager_client.patch(url, {"name": "x"}, format="json").status_code, 400)
        self.assertEqual(self.manager_client.delete(url).status_code, 400)
        r = self.manager_client.post(f"{url}add_controls/",
                                     {"controls": [self.tree.c2.pk]}, format="json")
        self.assertEqual(r.status_code, 400)
        row = PackageControl.objects.get(package=self.package)
        self.assertEqual(
            self.manager_client.delete(f"/api/package-controls/{row.pk}/").status_code, 400)


# --------------------------------------------------------------------------- #
# The disclosure boundary
# --------------------------------------------------------------------------- #
class DisclosureBoundaryTests(PackageTestBase):
    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        self.auditor_client = self.client_for(self.auditor)
        self.item = PackageEvidence.objects.get()

    def test_the_grantee_reads_pinned_bytes_with_no_folder_grant(self):
        # The premise: aria can see no folders at all.
        self.assertEqual(accessible_folder_ids(self.auditor), set())
        r = self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/file/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"policy bytes")

    def test_the_grant_widens_nothing_outside_the_package(self):
        """The bypass is for the packaged rows and nothing else."""
        c = self.auditor_client
        self.assertEqual(c.get(f"/api/documents/{self.doc.pk}/").status_code, 404)
        self.assertEqual(c.get(f"/api/documents/{self.doc.pk}/download/").status_code, 404)
        self.assertEqual(c.get("/api/documents/").data["count"], 0)
        self.assertEqual(c.get("/api/folders/tree/").data, [])
        self.assertEqual(c.get("/api/control-evidence/").data["count"], 0)

    def test_a_reader_of_one_package_cannot_read_another(self):
        other = EvidencePackage.objects.create(name="Someone else's", created_by=self.manager)
        row = PackageControl.objects.create(package=other, control_ref="X", title="X")
        item = PackageEvidence.objects.create(
            package_control=row, document=self.doc, document_name=self.doc.name)
        c = self.auditor_client
        self.assertEqual(c.get(f"/api/evidence-packages/{other.pk}/").status_code, 404)
        self.assertEqual(c.get(f"/api/package-evidence/{item.pk}/file/").status_code, 404)

    def test_every_byte_that_leaves_is_recorded_before_it_leaves(self):
        before = AuditLog.objects.filter(object_type="evidence-packages", action="read").count()
        self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/file/")
        entry = AuditLog.objects.filter(object_type="evidence-packages", action="read").latest("timestamp")
        self.assertEqual(
            AuditLog.objects.filter(object_type="evidence-packages", action="read").count(),
            before + 1)
        self.assertEqual(entry.user, self.auditor)
        self.assertIn("Access Control Policy", entry.detail)
        grant_row = PackageGrant.objects.get()
        self.assertEqual(grant_row.access_count, 1)
        self.assertIsNotNone(grant_row.last_accessed_at)

    def test_withdrawing_closes_access_on_the_next_request(self):
        r = self.manager_client.post(
            f"/api/evidence-packages/{self.package.pk}/withdraw/",
            {"reason": "Fieldwork complete"}, format="json")
        self.assertEqual(r.status_code, 200)
        c = self.auditor_client
        self.assertEqual(c.get(f"/api/package-evidence/{self.item.pk}/file/").status_code, 404)
        self.assertEqual(c.get("/api/evidence-packages/").data["count"], 0)
        # The grant survives as a record of what happened.
        self.assertIsNotNone(PackageGrant.objects.get().revoked_at)

    def test_an_expired_grant_stops_working_without_anyone_acting(self):
        PackageGrant.objects.update(expires_at=timezone.now() - timezone.timedelta(minutes=1))
        self.assertEqual(
            self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/file/").status_code, 404)

    def test_deactivating_or_demoting_the_auditor_revokes_on_the_next_request(self):
        self.auditor.role = self.roles["Viewer"]
        self.auditor.save()
        self.assertEqual(
            self.client_for(self.auditor).get(
                f"/api/package-controls/{PackageControl.objects.get().pk}/",
                ).status_code, 200,
            "reading is still allowed -- the grant is what governs that")
        # ...but writing a conclusion is not, because live_grant re-checks the role.
        r = self.client_for(self.auditor).patch(
            f"/api/package-controls/{PackageControl.objects.get().pk}/",
            {"design_conclusion": "no_exceptions"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_grant_on_a_draft_is_refused(self):
        """Otherwise 'seal small, grant, keep adding' would widen silently."""
        draft = EvidencePackage.objects.create(name="Draft", created_by=self.manager)
        r = self.manager_client.post("/api/package-grants/", {
            "package": draft.pk, "user": self.auditor.pk,
            "expires_at": (timezone.now() + timezone.timedelta(days=5)).isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_package_can_only_be_issued_to_an_active_auditor(self):
        for persona in (self.viewer, self.owner, self.admin):
            r = self.manager_client.post("/api/package-grants/", {
                "package": self.package.pk, "user": persona.pk,
                "expires_at": (timezone.now() + timezone.timedelta(days=5)).isoformat(),
            }, format="json")
            self.assertEqual(r.status_code, 400, f"{persona.username} should not be grantable")
        self.auditor.is_active = False
        self.auditor.save()
        PackageGrant.objects.all().delete()
        self.assertEqual(self.issue_to(self.auditor).status_code, 400)

    def test_a_grant_cannot_outlast_the_configured_ceiling(self):
        PackageGrant.objects.all().delete()
        self.assertEqual(self.issue_to(self.auditor, days=9999).status_code, 400)

    def test_control_owner_and_viewer_get_nothing(self):
        for persona in (self.owner, self.viewer):
            c = self.client_for(persona)
            self.assertEqual(c.get("/api/evidence-packages/").data["count"], 0,
                             f"{persona.username} must not see packages")
            self.assertEqual(c.get(f"/api/evidence-packages/{self.package.pk}/").status_code, 404)
            self.assertEqual(c.get(f"/api/package-evidence/{self.item.pk}/file/").status_code, 404)
            self.assertEqual(
                c.get(f"/api/evidence-packages/{self.package.pk}/export/").status_code, 404)

    def test_pinning_requires_visibility_and_is_not_launderable(self):
        """A frameworks role with no view-all can only package what it can see."""
        narrow_role = Role.objects.create(name="Narrow frameworks", can_manage_frameworks=True)
        narrow = make_user("nick", narrow_role)
        grant(self.tree.ctrl1, user=narrow, level=VIEW)
        hidden = make_doc(self.tree.ctrl2, owner=self.owner, name="Hidden evidence")
        # Linked to the control, so add_controls WILL encounter it -- and must
        # skip it rather than pin a document this packager cannot see.
        ControlEvidence.objects.create(control=self.tree.c2, document=hidden,
                                       linked_by=self.manager)
        c = self.client_for(narrow)

        own = c.post("/api/evidence-packages/", {"name": "Narrow package"}, format="json")
        self.assertEqual(own.status_code, 201)
        r = c.post(f"/api/evidence-packages/{own.data['id']}/add_controls/",
                   {"controls": [self.tree.c1.pk, self.tree.c2.pk]}, format="json")
        self.assertEqual(r.status_code, 201)
        row = PackageControl.objects.get(package_id=own.data["id"], control=self.tree.c1)

        # add_controls already pinned the visible document and skipped the
        # invisible one, reporting it rather than dropping it silently.
        self.assertEqual(
            [s["document"] for s in r.data["skipped"]], ["Hidden evidence"])
        self.assertTrue(PackageEvidence.objects.filter(
            package_control=row, document=self.doc).exists())

        # Pinning by hand follows the same rule: the visible document is
        # allowed onto another row, the invisible one is refused outright and
        # leaves nothing behind.
        other_row = PackageControl.objects.get(package_id=own.data["id"], control=self.tree.c2)
        ok = c.post("/api/package-evidence/",
                    {"package_control": other_row.pk, "document": self.doc.pk}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        before = PackageEvidence.objects.count()
        denied = c.post("/api/package-evidence/",
                        {"package_control": other_row.pk, "document": hidden.pk}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(PackageEvidence.objects.count(), before)

    def test_a_narrow_packager_cannot_read_other_peoples_packages(self):
        narrow_role = Role.objects.create(name="Narrow frameworks 2", can_manage_frameworks=True)
        narrow = make_user("nina", narrow_role)
        self.assertEqual(
            self.client_for(narrow).get(f"/api/evidence-packages/{self.package.pk}/").status_code,
            404)


# --------------------------------------------------------------------------- #
# Conclusions
# --------------------------------------------------------------------------- #
class ConclusionTests(PackageTestBase):
    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.issue_to(self.auditor)
        self.row = PackageControl.objects.get()

    def test_only_the_grantee_writes_conclusions(self):
        payload = {"design_conclusion": "no_exceptions"}
        url = f"/api/package-controls/{self.row.pk}/"
        # Those who can see the package are refused the write (403); those who
        # cannot see it at all are told nothing (404).
        for persona in (self.manager, self.admin):
            self.assertEqual(
                self.client_for(persona).patch(url, payload, format="json").status_code, 403,
                f"{persona.username} must not be able to conclude")
        self.assertEqual(
            self.client_for(self.owner).patch(url, payload, format="json").status_code, 404)
        r = self.client_for(self.auditor).patch(url, payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.row.refresh_from_db()
        self.assertEqual(self.row.design_conclusion, "no_exceptions")
        self.assertEqual(self.row.concluded_by, self.auditor)
        self.assertIsNotNone(self.row.concluded_at)

    def test_not_tested_has_to_say_why(self):
        url = f"/api/package-controls/{self.row.pk}/"
        c = self.client_for(self.auditor)
        r = c.patch(url, {"operating_conclusion": "not_tested"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not_tested_reason", r.data)
        r = c.patch(url, {"operating_conclusion": "not_tested",
                          "not_tested_reason": "Outside the period under review."}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_the_management_response_is_written_by_the_organisation_not_the_auditor(self):
        url = f"/api/package-controls/{self.row.pk}/"
        r = self.client_for(self.auditor).patch(
            url, {"management_response": "We disagree"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.manager_client.patch(url, {"management_response": "Remediated in Q4"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.responded_by, self.manager)

    def test_an_exception_can_be_promoted_into_the_risk_register(self):
        from governance.models import Risk

        url = f"/api/package-controls/{self.row.pk}/"
        self.client_for(self.auditor).patch(
            url, {"operating_conclusion": "exceptions",
                  "auditor_note": "Two of twenty-five samples lacked approval."}, format="json")
        r = self.manager_client.post(f"{url}promote/")
        self.assertEqual(r.status_code, 201, r.data)
        risk = Risk.objects.get(risk_type=Risk.Type.AUDIT_FINDING)
        self.assertIn("TC1.1", risk.title)
        self.assertEqual(risk.control, self.tree.c1)
        # ...and only once.
        self.assertEqual(self.manager_client.post(f"{url}promote/").status_code, 400)

    def test_a_control_without_exceptions_cannot_be_promoted(self):
        self.assertEqual(
            self.manager_client.post(f"/api/package-controls/{self.row.pk}/promote/").status_code,
            400)


# --------------------------------------------------------------------------- #
# The manifest and the bundle
# --------------------------------------------------------------------------- #
class ManifestTests(PackageTestBase):
    def test_the_manifest_is_byte_deterministic(self):
        payload = {"b": 2, "a": [3, {"z": 1, "y": 2}]}
        self.assertEqual(mf.canonical_bytes(payload), mf.canonical_bytes(dict(payload)))
        self.assertEqual(mf.canonical_bytes(payload), b'{"a":[3,{"y":2,"z":1}],"b":2}\n')

    def test_member_names_cannot_escape_the_bundle(self):
        name = mf.safe_member_name("../../etc/passwd.pdf", "evil.pdf", 1)
        self.assertEqual(name, "001-passwd.pdf")
        self.assertNotIn("..", name)
        self.assertNotIn("/", name)
        # The EXTENSION comes from the stored name, so a document called
        # "report.html" cannot land as executable content in the auditor's tree.
        self.assertTrue(mf.safe_member_name("report.html", "report.pdf", 2).endswith(".pdf"))
        self.assertEqual(mf.safe_segment("A.8.15"), "A_8_15")

    def test_the_manifest_carries_no_storage_path(self):
        self.add_control()
        self.seal()
        manifest = json.loads(self.package.manifest_json)
        blob = json.dumps(manifest)
        self.assertNotIn("/media/", blob)
        self.assertNotIn(self.doc.file.name, blob)
        self.assertNotIn("documents/", blob)
        item = manifest["controls"][0]["evidence"][0]
        self.assertEqual(item["sha256"], mf.sha256_hex(b"policy bytes"))
        self.assertTrue(item["path"].startswith("evidence/001-TC1_1/"))

    def test_the_stored_digest_matches_the_stored_manifest(self):
        self.add_control()
        self.seal()
        self.assertEqual(
            mf.sha256_hex(self.package.manifest_json.encode("utf-8")),
            self.package.manifest_sha256)


class BundleTests(PackageTestBase):
    def _export(self):
        self.add_control()
        self.seal()
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        return r, zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))

    def test_the_bundle_is_self_describing_and_self_verifying(self):
        response, zf = self._export()
        names = set(zf.namelist())
        for required in ("manifest.json", "MANIFEST.sha256", "SHA256SUMS", "README.txt",
                         "verify.py", "controls.csv", "evidence.csv", "trail.csv",
                         "INTEGRITY.txt"):
            self.assertIn(required, names)
        self.assertEqual(response["X-Conformiti-Integrity"], "ok")

        # The manifest in the bundle is the sealed one, byte for byte.
        self.assertEqual(zf.read("manifest.json").decode("utf-8"), self.package.manifest_json)
        recorded = zf.read("MANIFEST.sha256").decode("utf-8").split()[0]
        self.assertEqual(recorded, self.package.manifest_sha256)

        # Every SHA256SUMS line matches the member actually in the zip.
        for line in zf.read("SHA256SUMS").decode("utf-8").splitlines():
            digest, _, member = line.partition("  ")
            self.assertEqual(mf.sha256_hex(zf.read(member)), digest, member)

    def test_the_evidence_bytes_are_in_the_bundle_at_the_manifest_path(self):
        _, zf = self._export()
        manifest = json.loads(zf.read("manifest.json"))
        path = manifest["controls"][0]["evidence"][0]["path"]
        self.assertEqual(zf.read(path), b"policy bytes")

    def test_no_member_name_can_escape_on_extraction(self):
        _, zf = self._export()
        for name in zf.namelist():
            self.assertFalse(name.startswith("/"), name)
            self.assertNotIn("..", name.split("/"), name)

    def test_a_file_altered_after_sealing_is_reported_not_hidden(self):
        """The bundle must not lie, and must not disagree with itself."""
        self.add_control()
        self.seal()
        self.doc.file.save("swapped.txt", SimpleUploadedFile("swapped.txt", b"tampered"), save=True)
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("discrepancies=1", r["X-Conformiti-Integrity"])
        zf = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
        integrity = zf.read("INTEGRITY.txt").decode("utf-8")
        self.assertIn("NOT the bytes that were sealed", integrity)
        self.assertIn("ALTERED", zf.read("evidence.csv").decode("utf-8-sig"))
        # manifest keeps the SEALED digest; SHA256SUMS reports what is really here.
        manifest = json.loads(zf.read("manifest.json"))
        item = manifest["controls"][0]["evidence"][0]
        self.assertEqual(item["sha256"], mf.sha256_hex(b"policy bytes"))
        self.assertEqual(zf.read(item["path"]), b"tampered")

    def test_the_trail_extract_carries_no_ip_addresses(self):
        """This file is designed to leave the building."""
        _, zf = self._export()
        header = zf.read("trail.csv").decode("utf-8-sig").splitlines()[0]
        self.assertNotIn("IP", header.upper())

    def test_a_draft_cannot_be_exported(self):
        self.add_control()
        self.assertEqual(
            self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/").status_code,
            400)

    def test_the_grantee_can_export_and_it_is_recorded(self):
        self.add_control()
        self.seal()
        self.issue_to(self.auditor)
        r = self.client_for(self.auditor).get(
            f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        b"".join(r.streaming_content)
        entry = AuditLog.objects.filter(action="export").latest("timestamp")
        self.assertEqual(entry.user, self.auditor)

    def test_verify_reports_drift_without_exporting(self):
        self.add_control()
        self.seal()
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/verify/")
        self.assertTrue(r.data["ok"])
        self.doc.file.save("x.txt", SimpleUploadedFile("x.txt", b"changed again"), save=True)
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/verify/")
        self.assertFalse(r.data["ok"])
        self.assertEqual(len(r.data["discrepancies"]), 1)

    def test_the_shipped_verifier_refuses_unsafe_paths(self):
        from attestations import verifier

        for bad in ("/etc/passwd", "../secrets", "a/../../b", "C:/windows", ""):
            self.assertTrue(verifier.unsafe(bad), bad)
        for good in ("manifest.json", "evidence/001-TC1_1/001-policy.txt"):
            self.assertFalse(verifier.unsafe(good), good)
