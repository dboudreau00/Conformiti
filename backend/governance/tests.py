"""Access reviews, risk register, meetings — permissions and export safety."""
import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from governance.models import AccessReview, AccessReviewItem, Risk
from governance.risk_import import normalize, parse_upload
from testutils import APITestBase


class AccessReviewTests(APITestBase):
    def test_lifecycle_and_permissions(self):
        self.viewer.first_name = "=1+1"
        self.viewer.save()
        admin = self.client_for(self.admin)
        r = admin.post("/api/access-reviews/", {"name": "Q3 review"}, format="json")
        self.assertEqual(r.status_code, 201)
        rid = r.data["id"]
        items = admin.get(f"/api/access-review-items/?review={rid}").data
        self.assertEqual(len(items), 5)  # unpaginated, one row per account
        self.assertEqual(r.data["item_count"], 5)

        # auditors read, never write; viewers see nothing
        aud = self.client_for(self.auditor)
        self.assertEqual(aud.get("/api/access-reviews/").status_code, 200)
        self.assertEqual(aud.patch(f"/api/access-review-items/{items[0]['id']}/", {"decision": "keep"}, format="json").status_code, 403)
        self.assertEqual(aud.post(f"/api/access-reviews/{rid}/complete/").status_code, 403)
        self.assertEqual(self.client_for(self.viewer).get("/api/access-reviews/").status_code, 403)

        # completing with pending rows is refused
        r = admin.post(f"/api/access-reviews/{rid}/complete/")
        self.assertEqual(r.status_code, 400)
        for it in items:
            r = admin.patch(f"/api/access-review-items/{it['id']}/", {"decision": "keep", "decision_notes": "ok"}, format="json")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data["decided_by"], self.admin.pk)
        r = admin.post(f"/api/access-reviews/{rid}/complete/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "completed")
        # read-only afterwards
        self.assertEqual(admin.patch(f"/api/access-review-items/{items[0]['id']}/", {"decision": "revoke"}, format="json").status_code, 400)
        self.assertEqual(admin.post(f"/api/access-reviews/{rid}/complete/").status_code, 400)

        # CSV export neutralises formula injection
        export = admin.get(f"/api/access-reviews/{rid}/export/")
        self.assertEqual(export["Content-Type"], "text/csv")
        rows = list(csv.reader(io.StringIO(export.content.decode())))
        self.assertEqual(rows[0][0], "Username")
        val_row = next(r for r in rows if r[0] == "val")
        self.assertEqual(val_row[1], "'=1+1 Tester")

    def test_snapshot_is_stable_after_account_changes(self):
        admin = self.client_for(self.admin)
        rid = admin.post("/api/access-reviews/", {"name": "R"}, format="json").data["id"]
        self.owner.role = None
        self.owner.save()
        row = AccessReviewItem.objects.get(review_id=rid, username="owen")
        self.assertEqual(row.role_name, "Control Owner")


class RiskRegisterTests(APITestBase):
    def test_permissions(self):
        v = self.client_for(self.viewer)
        payload = {"title": "Laptops unencrypted", "likelihood": 4, "impact": 4}
        self.assertEqual(v.post("/api/risks/", payload, format="json").status_code, 403)
        m = self.client_for(self.manager)
        r = m.post("/api/risks/", {**payload, "owner": self.owner.pk, "control": self.tree.c1.pk}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["rating"], "critical")
        rid = r.data["id"]
        # everyone can read
        self.assertEqual(v.get(f"/api/risks/{rid}/").status_code, 200)
        # owner may update their own risk; viewer may not
        self.assertEqual(self.client_for(self.owner).patch(f"/api/risks/{rid}/", {"status": "mitigating"}, format="json").status_code, 200)
        self.assertEqual(v.patch(f"/api/risks/{rid}/", {"status": "closed"}, format="json").status_code, 403)
        # only managers delete
        self.assertEqual(self.client_for(self.owner).delete(f"/api/risks/{rid}/").status_code, 403)
        # bounds
        self.assertEqual(m.patch(f"/api/risks/{rid}/", {"likelihood": 9}, format="json").status_code, 400)
        # closing stamps closed_at, reopening clears it
        r = m.patch(f"/api/risks/{rid}/", {"status": "closed"}, format="json")
        self.assertIsNotNone(r.data["closed_at"])
        r = m.patch(f"/api/risks/{rid}/", {"status": "open"}, format="json")
        self.assertIsNone(r.data["closed_at"])
        # notes: anyone may add, only author or manager may delete
        n = v.post("/api/risk-notes/", {"risk": rid, "text": "seen it"}, format="json")
        self.assertEqual(n.status_code, 201)
        self.assertEqual(self.client_for(self.owner).delete(f"/api/risk-notes/{n.data['id']}/").status_code, 403)
        self.assertEqual(v.delete(f"/api/risk-notes/{n.data['id']}/").status_code, 204)
        self.assertEqual(m.delete(f"/api/risks/{rid}/").status_code, 204)

    def test_import_creates_dedupes_and_warns(self):
        csv_bytes = (
            "Title;Probability;Severity;Owner;Control;Due date;Status;Notes\n"
            "Vendor SOC report expired;High;4;owen;TC1.1;2026-12-01;Open;chase vendor\n"
            "Mystery;banana;2;ghost;nope;31/12/2026;Done;\n"
            ";1;1;;;;;\n"
        ).encode()
        m = self.client_for(self.manager)
        r = m.post("/api/risks/import/", {"file": SimpleUploadedFile("reg.csv", csv_bytes)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 2)
        messages = " ".join(w["message"] for w in r.data["warnings"])
        self.assertIn("likelihood", messages)
        self.assertIn("Owner 'ghost'", messages)
        self.assertIn("Control 'nope'", messages)
        first = Risk.objects.get(title="Vendor SOC report expired")
        self.assertEqual(first.owner, self.owner)
        self.assertEqual(first.control, self.tree.c1)
        self.assertEqual(first.likelihood, 4)
        self.assertEqual(first.notes.count(), 1)
        self.assertEqual(Risk.objects.get(title="Mystery").status, "closed")
        # second import: everything skipped as duplicate
        r = m.post("/api/risks/import/", {"file": SimpleUploadedFile("reg.csv", csv_bytes)}, format="multipart")
        self.assertEqual(r.data["created"], 0)
        self.assertEqual(len(r.data["skipped"]), 2)
        # viewers cannot import; bad files give 400s not 500s
        self.assertEqual(self.client_for(self.viewer).post("/api/risks/import/", {"file": SimpleUploadedFile("r.csv", b"Title\nx")}, format="multipart").status_code, 403)
        self.assertEqual(m.post("/api/risks/import/", {"file": SimpleUploadedFile("r.xlsx", b"not a zip")}, format="multipart").status_code, 400)
        self.assertEqual(m.post("/api/risks/import/", {"file": SimpleUploadedFile("r.docx", b"x")}, format="multipart").status_code, 400)
        # a sheet with no recognisable Title column is rejected cleanly
        self.assertEqual(m.post("/api/risks/import/", {"file": SimpleUploadedFile("r.csv", b"Widget\nrow")}, format="multipart").status_code, 400)
        # ...while "Name" is accepted as a title alias
        r = m.post("/api/risks/import/", {"file": SimpleUploadedFile("r.csv", b"Name\nUntitled register row")}, format="multipart")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["created"], 1)

    def test_importer_is_pure(self):
        recs, issues, fatal = normalize(parse_upload("t.csv", b"Title,Impact\nA,Critical\n"))
        self.assertIsNone(fatal)
        self.assertEqual(recs[0]["impact"], 5)
        recs, issues, fatal = normalize(parse_upload("t.csv", b"Nope\n1\n"))
        self.assertIsNotNone(fatal)

    def test_export_and_summary(self):
        m = self.client_for(self.manager)
        m.post("/api/risks/", {"title": "=cmd|' /C calc'!A0", "likelihood": 1, "impact": 1, "due_date": "2000-01-01"}, format="json")
        m.post("/api/risks/", {"title": "Closed one", "likelihood": 2, "impact": 2, "status": "closed"}, format="json")
        s = m.get("/api/risks/summary/").data
        self.assertEqual(s["open"], 1)
        self.assertEqual(s["overdue"], 1)
        self.assertEqual(s["closed"], 1)
        export = self.client_for(self.viewer).get("/api/risks/export/")
        rows = list(csv.reader(io.StringIO(export.content.decode())))
        titles = [r[0] for r in rows[1:]]
        self.assertIn("'=cmd|' /C calc'!A0", titles)


class MeetingAndGroupTests(APITestBase):
    def test_cadence_maths_and_write_gates(self):
        v = self.client_for(self.viewer)
        m = self.client_for(self.manager)
        self.assertEqual(v.post("/api/meeting-series/", {"name": "Steering", "required_per_year": 4}, format="json").status_code, 403)
        r = m.post("/api/meeting-series/", {"name": "Steering", "required_per_year": 4, "owner": self.manager.pk}, format="json")
        self.assertEqual(r.status_code, 201)
        sid = r.data["id"]
        self.assertIn(r.data["cadence_status"], ("behind", "on_track", "complete"))
        # minutes: attachment obeys the upload rules
        with override_settings(MAX_UPLOAD_BYTES=4, MAX_UPLOAD_MB=1):
            r = m.post("/api/meeting-minutes/", {"series": sid, "date": "2026-01-15", "file": SimpleUploadedFile("m.pdf", b"12345")}, format="multipart")
            self.assertEqual(r.status_code, 400)
        r = m.post("/api/meeting-minutes/", {"series": sid, "date": "2026-01-15", "title": "Q1"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["created_by"], self.manager.pk)
        # groups are admin-managed
        self.assertEqual(m.post("/api/champion-groups/", {"name": "Champs"}, format="json").status_code, 403)
        g = self.client_for(self.admin).post("/api/champion-groups/", {"name": "Champs", "owner": self.manager.pk}, format="json")
        self.assertEqual(g.status_code, 201)
        r = self.client_for(self.admin).post("/api/group-members/", {"group": g.data["id"], "user": self.owner.pk, "department": "Eng"}, format="json")
        self.assertEqual(r.status_code, 201)
        # duplicate membership is a 400, not a 500
        r = self.client_for(self.admin).post("/api/group-members/", {"group": g.data["id"], "user": self.owner.pk, "department": "Eng"}, format="json")
        self.assertEqual(r.status_code, 400)
