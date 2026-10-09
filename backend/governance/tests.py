"""Access reviews, risk register, meetings: permissions and export safety."""
import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from governance.models import AccessReviewItem, Risk
from governance.risk_import import normalize, parse_upload
from testutils import APITestBase, make_xlsx


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

    def test_an_owner_changes_only_the_remediation_fields(self):
        m = self.client_for(self.manager)
        rid = m.post("/api/risks/", {"title": "Shared admin account", "likelihood": 3, "impact": 3,
                                      "owner": self.owner.pk}, format="json").data["id"]
        o = self.client_for(self.owner)
        ok = o.patch(f"/api/risks/{rid}/", {"status": "mitigating", "mitigation_plan": "rotate",
                                             "due_date": "2027-01-31", "jira_key": "SEC-9"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        for field, value in (("owner", self.viewer.pk), ("owner", None), ("likelihood", 1),
                             ("impact", 5), ("treatment", "accept"), ("title", "Renamed"),
                             ("control", self.tree.c1.pk)):
            with self.subTest(field=field, value=value):
                r = o.patch(f"/api/risks/{rid}/", {field: value}, format="json")
                self.assertEqual(r.status_code, 400, r.data)
                self.assertIn(field, r.data)
        # Sending a field back unchanged is not a change (a form posts it all).
        r = o.patch(f"/api/risks/{rid}/", {"title": "Shared admin account", "owner": self.owner.pk,
                                           "status": "open"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        # A manager keeps the lot.
        self.assertEqual(m.patch(f"/api/risks/{rid}/", {"owner": self.viewer.pk, "likelihood": 1},
                                 format="json").status_code, 200)

    def test_a_decision_cannot_land_on_a_completed_review(self):
        admin = self.client_for(self.admin)
        rid = admin.post("/api/access-reviews/", {"name": "R"}, format="json").data["id"]
        items = admin.get(f"/api/access-review-items/?review={rid}").data
        for it in items:
            admin.patch(f"/api/access-review-items/{it['id']}/", {"decision": "keep"}, format="json")
        self.assertEqual(admin.post(f"/api/access-reviews/{rid}/complete/").status_code, 200)
        r = admin.patch(f"/api/access-review-items/{items[0]['id']}/", {"decision": "revoke"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(AccessReviewItem.objects.get(pk=items[0]["id"]).decision, "keep")

    def test_xlsx_with_a_doctype_is_refused(self):
        import zipfile
        good = make_xlsx([["Title"], ["Backups"]])
        src = zipfile.ZipFile(io.BytesIO(good))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for name in src.namelist():
                data = src.read(name)
                if name.startswith("xl/worksheets/sheet"):
                    data = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>' + data.split(b"?>", 1)[-1]
                zf.writestr(name, data)
        with self.assertRaises(ValueError):
            parse_upload("register.xlsx", out.getvalue())
        self.assertEqual(parse_upload("register.xlsx", good)[1], ["Backups"])

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


class SpreadsheetEscapeTests(APITestBase):
    """Excel writes a character XML cannot carry as _xHHHH_ (a carriage return
    in a cell is "_x000D_") and the underscore of a literal one as _x005F_.
    The reader decodes them in shared strings, inline strings and cached
    formula text, and leaves alone what only looks like an escape."""

    STORAGES = ("inline", "shared", "formula")

    def read(self, rows, storage):
        return parse_upload("register.xlsx", make_xlsx(rows, storage))

    def test_a_carriage_return_is_decoded(self):
        for storage in self.STORAGES:
            with self.subTest(storage=storage):
                rows = self.read([["Title", "Description"], ["Backups", "Line one_x000D__x000A_Line two"]], storage)
                self.assertEqual(rows[1], ["Backups", "Line one\r\nLine two"])

    def test_a_carriage_return_after_a_header_does_not_hide_the_column(self):
        for storage in self.STORAGES:
            with self.subTest(storage=storage):
                recs, _, fatal = normalize(self.read([["Title_x000D_", "Status"], ["Backups", "Open"]], storage))
                self.assertIsNone(fatal)
                self.assertEqual(recs[0]["title"], "Backups")

    def test_an_escaped_literal_reads_as_the_text_it_stood_for(self):
        for storage in self.STORAGES:
            with self.subTest(storage=storage):
                rows = self.read([["Ref"], ["_x005F_x0041_"], ["_x005F_x005F_"]], storage)
                self.assertEqual(rows[1:], [["_x0041_"], ["_x005F_"]])

    def test_a_surrogate_pair_becomes_one_character(self):
        for storage in self.STORAGES:
            with self.subTest(storage=storage):
                rows = self.read([["Ref"], ["Alert _xD83D__xDE00_"], ["Alert _xd83d__xde00_"]], storage)
                self.assertEqual(rows[1:], [["Alert \U0001F600"], ["Alert \U0001F600"]])

    def test_text_that_only_looks_like_an_escape_is_left_alone(self):
        lookalikes = ["_x12_", "_xZZZZ_", "_x00041_", "_X0041_", "_x0041", "x0041_"]
        for storage in self.STORAGES:
            with self.subTest(storage=storage):
                rows = self.read([["Ref"], *[[t] for t in lookalikes]], storage)
                self.assertEqual(rows[1:], [[t] for t in lookalikes])

    def test_an_import_stores_the_decoded_text(self):
        rows = [["Title", "Description", "Notes"],
                ["Vendor _x005F_x0041_ outage", "First line_x000D__x000A_Second line", "Seen _xD83D__xDE00_"]]
        r = self.client_for(self.manager).post(
            "/api/risks/import/", {"file": SimpleUploadedFile("reg.xlsx", make_xlsx(rows, "shared"))},
            format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 1)
        risk = Risk.objects.get(title="Vendor _x0041_ outage")
        self.assertEqual(risk.description, "First line\r\nSecond line")
        self.assertEqual(risk.notes.get().text, "Seen \U0001F600")

    def test_an_escape_that_cannot_be_stored_does_not_break_the_import(self):
        """A NUL is refused by PostgreSQL and a lone surrogate cannot be encoded
        as UTF-8, so neither is decoded: each stays as written."""
        rows = [["Title", "Description"], ["Nul_x0000_", "x"], ["Half_xD83D_", "y"]]
        r = self.client_for(self.manager).post(
            "/api/risks/import/", {"file": SimpleUploadedFile("reg.xlsx", make_xlsx(rows))}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 2)
        self.assertEqual(set(Risk.objects.values_list("title", flat=True)), {"Nul_x0000_", "Half_xD83D_"})


class NamelessAccountExportTests(APITestBase):
    """createsuperuser asks for no first or last name, so both CSV exports
    must carry the username in such a person's column. A full name still
    wins, and an empty value stays blank."""

    def setUp(self):
        super().setUp()
        from testutils import make_user

        self.root = make_user("rootadmin", self.roles["Administrator"], superuser=True,
                              first_name="", last_name="")

    @staticmethod
    def _rows(response, key):
        return {row[key]: row for row in csv.DictReader(io.StringIO(response.content.decode()))}

    def test_the_access_review_names_who_decided(self):
        rid = self.client_for(self.admin).post("/api/access-reviews/", {"name": "Q3"}, format="json").data["id"]
        for deciding, username in ((self.root, "owen"), (self.admin, "mia")):
            item = AccessReviewItem.objects.get(review_id=rid, username=username)
            r = self.client_for(deciding).patch(f"/api/access-review-items/{item.pk}/",
                                                {"decision": "keep"}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
        rows = self._rows(self.client_for(self.admin).get(f"/api/access-reviews/{rid}/export/"), "Username")
        self.assertEqual(rows["owen"]["Decided by"], "rootadmin")
        self.assertEqual(rows["mia"]["Decided by"], "Ada Tester")
        self.assertEqual(rows["val"]["Decided by"], "")

    def test_the_risk_register_names_the_owner(self):
        Risk.objects.create(title="Root's risk", owner=self.root, created_by=self.root)
        Risk.objects.create(title="Owen's risk", owner=self.owner, created_by=self.root)
        Risk.objects.create(title="Nobody's risk", created_by=self.root)
        rows = self._rows(self.client_for(self.viewer).get("/api/risks/export/"), "Title")
        self.assertEqual(rows["Root's risk"]["Owner"], "rootadmin")
        self.assertEqual(rows["Owen's risk"]["Owner"], "Owen Tester")
        self.assertEqual(rows["Nobody's risk"]["Owner"], "")


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

    def test_required_per_year_is_held_to_once_a_year_up_to_weekly(self):
        """0 would read as "complete" at once and the model field takes up to
        32767, so the API refuses both ends rather than storing them."""
        m = self.client_for(self.manager)
        for bad in (0, 53):
            r = m.post("/api/meeting-series/", {"name": f"Bad {bad}", "required_per_year": bad}, format="json")
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("required_per_year", r.data)
        r = m.post("/api/meeting-series/", {"name": "Weekly", "required_per_year": 52}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["required_per_year"], 52)
        # an edit is held to the same range
        r = m.patch(f"/api/meeting-series/{r.data['id']}/", {"required_per_year": 100}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("required_per_year", r.data)
