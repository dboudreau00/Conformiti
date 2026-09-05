"""
Vendor risk: the register, assurance posture, the shared responsibility
matrix, the import recogniser, and how vendors surface in RACI, readiness and
the notifications feed.
"""
import io
import zipfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from compliance import scoring
from compliance.models import Control, Responsibility
from documents.models import VIEW
from governance.models import Risk
from notifications.notifications import build as build_feed
from testutils import APITestBase, grant, make_doc
from vendors import matrix as mx
from vendors.models import SharedResponsibility, Vendor, VendorAssessment


def _vendor(**extra):
    defaults = dict(name="Northwind Cloud", category="Cloud hosting", tier="critical",
                    data_handled="customer PII")
    defaults.update(extra)
    return Vendor.objects.create(**defaults)


def _xlsx(rows):
    """A minimal .xlsx with one sheet and inline strings -- enough for the
    stdlib reader the importer sits on."""
    def cell(ref, value):
        text = str(value).replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
    sheet_rows = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(cell(f"{chr(65 + c)}{r}", v) for c, v in enumerate(row))
        sheet_rows.append(f'<row r="{r}">{cells}</row>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             'spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + '</sheetData></worksheet>')
    workbook = ('<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships"><sheets><sheet name="Matrix" sheetId="1" '
                'r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Id="rId1" Type="x" '
            'Target="worksheets/sheet1.xml"/></Relationships>')
    types = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
             '2006/content-types"></Types>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", types)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Register
# --------------------------------------------------------------------------- #
class VendorRegisterTests(APITestBase):
    def test_everyone_reads_and_only_the_frameworks_capability_writes(self):
        v = _vendor()
        self.assertEqual(self.client_for(self.viewer).get("/api/vendors/").data["count"], 1)
        self.assertEqual(
            self.client_for(self.viewer).post("/api/vendors/", {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(
            self.client_for(self.owner).patch(f"/api/vendors/{v.pk}/", {"tier": "low"}, format="json").status_code, 403)
        r = self.client_for(self.manager).post("/api/vendors/", {
            "name": "Payroll Co", "tier": "high", "review_cadence": "annual"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNotNone(r.data["next_review_date"], "creating sets the review clock")

    def test_website_must_be_https(self):
        r = self.client_for(self.manager).post("/api/vendors/", {
            "name": "Plain", "website": "http://plain.example"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("website", r.data)

    def test_marking_reviewed_resets_the_clock(self):
        v = _vendor(review_cadence="quarterly")
        r = self.client_for(self.manager).post(f"/api/vendors/{v.pk}/mark_reviewed/")
        self.assertEqual(r.status_code, 200)
        v.refresh_from_db()
        self.assertEqual(v.last_reviewed, timezone.localdate())
        self.assertEqual(v.next_review_date, timezone.localdate() + timedelta(days=91))

    def test_the_review_clock_counts_from_onboarding_and_ignores_unrelated_edits(self):
        c = self.client_for(self.manager)
        v = c.post("/api/vendors/", {"name": "Clock Co", "review_cadence": "annual"}, format="json").data
        due = timezone.localdate() + timedelta(days=365)
        self.assertEqual(v["next_review_date"], due.isoformat())
        v = c.patch(f"/api/vendors/{v['id']}/", {"notes": "edited"}, format="json").data
        self.assertEqual(v["next_review_date"], due.isoformat(), "a notes edit must not move the clock")
        v = c.patch(f"/api/vendors/{v['id']}/", {"review_cadence": "quarterly"}, format="json").data
        self.assertEqual(v["next_review_date"], (timezone.localdate() + timedelta(days=91)).isoformat())
        # A vendor onboarded long ago and never reviewed is overdue, and stays so.
        old = _vendor(name="Old Hand")
        Vendor.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        old.refresh_from_db()
        old.compute_next_review()
        old.save()
        v = c.patch(f"/api/vendors/{old.pk}/", {"notes": "still here"}, format="json").data
        self.assertTrue(v["is_review_overdue"])

    def test_the_register_list_does_not_grow_queries_with_vendors(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(6):
            _vendor(name=f"Vendor {i}")
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client_for(self.viewer).get("/api/vendors/").status_code, 200)
        self.assertLess(len(ctx.captured_queries), 12, len(ctx.captured_queries))

    def test_export_is_csv(self):
        _vendor()
        r = self.client_for(self.manager).get("/api/vendors/export/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Northwind Cloud", r.content.decode("utf-8"))


class AssuranceTests(APITestBase):
    def _assess(self, vendor, **extra):
        defaults = dict(kind="soc2_type2", result="satisfactory",
                        issued_at=timezone.localdate() - timedelta(days=30),
                        expires_at=timezone.localdate() + timedelta(days=335))
        defaults.update(extra)
        return VendorAssessment.objects.create(vendor=vendor, **defaults)

    def test_posture_follows_the_assessments(self):
        v = _vendor()
        self.assertEqual(v.assurance()["posture"], "none")
        a = self._assess(v)
        self.assertEqual(v.assurance()["posture"], "current")
        a.expires_at = timezone.localdate() - timedelta(days=1)
        a.save()
        self.assertEqual(v.assurance()["posture"], "expired")
        self._assess(v, kind="pentest")
        self.assertEqual(v.assurance()["posture"], "partial")
        self._assess(v, kind="dpa", result="unsatisfactory")
        self.assertEqual(v.assurance()["posture"], "unsatisfactory")

    def test_risk_rating_crosses_tier_with_posture(self):
        """A critical vendor with nothing on file is the case this exists for."""
        critical = _vendor(name="A", tier="critical")
        self.assertEqual(critical.risk_rating(), "critical")
        self._assess(critical)
        self.assertEqual(critical.risk_rating(), "high", "tier alone keeps it high")
        low = _vendor(name="B", tier="low")
        self.assertEqual(low.risk_rating(), "high", "no assurance is never 'low'")
        self._assess(low)
        self.assertEqual(low.risk_rating(), "low")

    def test_a_report_must_be_a_document_the_caller_can_see(self):
        v = _vendor()
        hidden = make_doc(self.tree.ctrl2, owner=self.owner, name="SOC report")
        narrow_role = self.roles["Compliance Manager"]
        narrow_role.can_view_all = False
        narrow_role.can_manage_folders = False   # the other folder-wide bypass
        narrow_role.save()
        r = self.client_for(self.manager).post("/api/vendor-assessments/", {
            "vendor": v.pk, "kind": "soc2_type2", "document": hidden.pk}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("document", r.data)

    def test_questionnaire_answers_are_validated_against_the_shipped_questions(self):
        v = _vendor()
        c = self.client_for(self.manager)
        bad = c.post("/api/vendor-assessments/", {
            "vendor": v.pk, "kind": "questionnaire",
            "answers": {"made_up": {"answer": "yes"}}}, format="json")
        self.assertEqual(bad.status_code, 400)
        bad = c.post("/api/vendor-assessments/", {
            "vendor": v.pk, "kind": "questionnaire",
            "answers": {"soc2": {"answer": "maybe"}}}, format="json")
        self.assertEqual(bad.status_code, 400)
        ok = c.post("/api/vendor-assessments/", {
            "vendor": v.pk, "kind": "questionnaire",
            "answers": {"soc2": {"answer": "yes", "note": "Report on file"},
                        "dpa": {"answer": "partial"}}}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data["reviewed_by_name"], self.manager.get_full_name())

    def test_a_reader_without_the_folder_learns_a_copy_exists_but_not_which(self):
        """The writer-side check has a mirror on the way out: the assessment
        must not become an index of documents behind folder permissions."""
        v = _vendor()
        hidden = make_doc(self.tree.ctrl2, owner=self.owner, name="Northwind SOC 2 - qualified opinion")
        r = self.client_for(self.manager).post("/api/vendor-assessments/", {
            "vendor": v.pk, "kind": "soc2_type2", "document": hidden.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        for url in ("/api/vendor-assessments/", f"/api/vendors/{v.pk}/"):
            data = self.client_for(self.viewer).get(url).data
            row = (data["results"] if "results" in data else data["assessments"])[0]
            self.assertIsNone(row["document"], url)
            self.assertIsNone(row["document_name"], url)
            self.assertTrue(row["document_hidden"], url)
        grant(self.tree.ctrl2, user=self.viewer, level=VIEW)
        row = self.client_for(self.viewer).get("/api/vendor-assessments/").data["results"][0]
        self.assertEqual(row["document_name"], hidden.name)
        self.assertFalse(row["document_hidden"])

    def test_the_aoc_and_their_matrix_can_be_filed_as_documents(self):
        v = _vendor()
        aoc = make_doc(self.tree.ctrl1, owner=self.owner, name="Northwind AOC 2026")
        matrix_doc = make_doc(self.tree.ctrl1, owner=self.owner, name="Northwind responsibility matrix")
        c = self.client_for(self.manager)
        for kind, doc in (("pci_aoc", aoc), ("resp_matrix", matrix_doc)):
            r = c.post("/api/vendor-assessments/", {
                "vendor": v.pk, "kind": kind, "document": doc.pk,
                "expires_at": str(timezone.localdate() + timedelta(days=365))}, format="json")
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(r.data["document_name"], doc.name)
        detail = c.get(f"/api/vendors/{v.pk}/").data
        self.assertEqual({a["kind"] for a in detail["assessments"]}, {"pci_aoc", "resp_matrix"})


# --------------------------------------------------------------------------- #
# Shared responsibility matrix
# --------------------------------------------------------------------------- #
class MatrixTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.v = _vendor()
        self.c = self.client_for(self.manager)

    def test_the_grid_lists_every_control_with_blanks(self):
        r = self.c.get(f"/api/vendors/{self.v.pk}/matrix/?framework=tfw")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["summary"], {"controls": 2, "stated": 0, "unstated": 2})
        self.assertIsNone(r.data["rows"][0]["responsibility"])

    def test_saving_the_grid_upserts_and_clearing_removes(self):
        r = self.c.put(f"/api/vendors/{self.v.pk}/matrix/", {"rows": [
            {"control": self.tree.c1.pk, "responsibility": "provider",
             "provider_statement": "Physical security of the data centre."},
            {"control": self.tree.c2.pk, "responsibility": "shared",
             "provider_statement": "Platform patching.", "customer_statement": "Guest OS patching."},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data, {"saved": 2, "cleared": 0})
        r = self.c.get(f"/api/vendors/{self.v.pk}/matrix/").data
        self.assertEqual(r["summary"]["stated"], 2)
        # Clearing one
        r = self.c.put(f"/api/vendors/{self.v.pk}/matrix/", {"rows": [
            {"control": self.tree.c1.pk, "responsibility": None}]}, format="json")
        self.assertEqual(r.data, {"saved": 0, "cleared": 1})
        self.assertEqual(SharedResponsibility.objects.filter(vendor=self.v).count(), 1)

    def test_the_grid_validates_before_it_writes(self):
        r = self.c.put(f"/api/vendors/{self.v.pk}/matrix/", {"rows": [
            {"control": self.tree.c1.pk, "responsibility": "provider"},
            {"control": 999999, "responsibility": "provider"},
        ]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(SharedResponsibility.objects.count(), 0, "nothing written on a bad row")
        r = self.c.put(f"/api/vendors/{self.v.pk}/matrix/", {"rows": [
            {"control": self.tree.c1.pk, "responsibility": "everyone"}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_only_the_frameworks_capability_writes_the_grid(self):
        r = self.client_for(self.owner).put(f"/api/vendors/{self.v.pk}/matrix/", {"rows": []},
                                            format="json")
        self.assertEqual(r.status_code, 403)

    def test_export_is_the_grid_as_csv(self):
        SharedResponsibility.objects.create(vendor=self.v, control=self.tree.c1,
                                            responsibility="shared", provider_statement="Theirs")
        r = self.c.get(f"/api/vendors/{self.v.pk}/matrix/export/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8")
        self.assertIn("TC1.1", body)
        self.assertIn("shared", body)

    def test_a_vendor_that_shares_a_control_shows_as_responsible_in_the_raci_matrix(self):
        SharedResponsibility.objects.create(vendor=self.v, control=self.tree.c1,
                                            responsibility="provider")
        r = self.c.get("/api/responsibilities/matrix/?framework=tfw")
        row = next(x for x in r.data["rows"] if x["control"] == self.tree.c1.pk)
        self.assertTrue(row["shared"])
        self.assertEqual(row["responsible"][0]["name"], "Northwind Cloud")
        self.assertTrue(row["responsible"][0]["implicit"])


class ImportRecognitionTests(APITestBase):
    """The vendor's file, whatever shape it came in."""

    def setUp(self):
        super().setUp()
        self.v = _vendor(name="Northwind")
        self.c = self.client_for(self.manager)
        self.refs = {mx.normalise_ref(c.control_id): c.pk for c in Control.objects.all()}

    def test_control_references_normalise_to_the_register(self):
        for raw, expected in [("Req 8.3.6", "8.3.6"), ("PCI DSS 8.3.6.", "8.3.6"),
                              ("Requirement 1.2", "1.2"), ("CC 6.1", "CC6.1"),
                              ("A5.15", "A.5.15"), ("A-5.15", "A.5.15"), ("a.5.15", "A.5.15"),
                              ("TC1.1", "TC1.1")]:
            self.assertEqual(mx.normalise_ref(raw), expected, raw)

    def test_prose_responsibility_column(self):
        csv = ("Requirement,Responsibility,Provider statement,Customer statement\n"
               "TC1.1,Shared,We patch the platform,You patch the guest\n"
               "TC1.2,Service Provider,All ours,\n").encode()
        out = mx.recognise("m.csv", csv, "Northwind", self.refs)
        self.assertEqual(out["summary"]["matched"], 2)
        by = {r["ref"]: r for r in out["rows"]}
        self.assertEqual(by["TC1.1"]["responsibility"], "shared")
        self.assertEqual(by["TC1.2"]["responsibility"], "provider")
        self.assertEqual(by["TC1.1"]["customer_statement"], "You patch the guest")

    def test_two_mark_columns_in_the_pci_layout(self):
        """AWS-style: X under the provider, X under the customer, both = shared."""
        csv = ("Req #,Northwind,Customer\n"
               "TC1.1,X,\n"
               "TC1.2,X,X\n").encode()
        out = mx.recognise("m.csv", csv, "Northwind", self.refs)
        by = {r["ref"]: r for r in out["rows"]}
        self.assertEqual(by["TC1.1"]["responsibility"], "provider")
        self.assertEqual(by["TC1.2"]["responsibility"], "shared")
        roles = {c["role"] for c in out["columns"] if c["role"]}
        self.assertIn("provider_mark", roles)
        self.assertIn("customer_mark", roles)

    def test_the_vendors_acronym_and_an_unnamed_mark_column_are_read_as_marks(self):
        """AWS writes "AWS" at the top of its column, not "Amazon Web Services";
        and a vendor we know by a name that appears nowhere in the file still
        gets its column, because a column of X's beside "Customer" can only be
        the provider."""
        refs = self.refs
        csv = "Requirement,AWS,Customer\n1.3,X,X\n12.1,,X\n".replace("1.3", "TC1.1").replace("12.1", "TC1.2").encode()
        out = mx.recognise("m.csv", csv, "Amazon Web Services", refs)
        roles = {c["column"]: c["role"] for c in out["columns"]}
        self.assertEqual(roles["AWS"], "provider_mark")
        self.assertEqual(roles["Customer"], "customer_mark")
        by = {r["ref"]: r for r in out["rows"]}
        self.assertEqual(by["TC1.1"]["responsibility"], "shared")
        self.assertEqual(by["TC1.2"]["responsibility"], "customer")
        self.assertEqual(by["TC1.1"]["provider_statement"], "", "an X is a mark, not a statement")
        out = mx.recognise("m.csv", b"Requirement,Northwind Cloud Ltd,Customer\nTC1.1,X,\n", "Zephyr", refs)
        roles = {c["column"]: c["role"] for c in out["columns"]}
        self.assertEqual(roles["Northwind Cloud Ltd"], "provider_mark")
        self.assertEqual(out["rows"][0]["responsibility"], "provider")

    def test_the_vendors_own_name_is_recognised_as_the_provider_side(self):
        csv = "Control,Northwind responsibility,Merchant responsibility\nTC1.1,Encrypts at rest,Manages keys\n".encode()
        out = mx.recognise("m.csv", csv, "Northwind", self.refs)
        row = out["rows"][0]
        self.assertEqual(row["provider_statement"], "Encrypts at rest")
        self.assertEqual(row["customer_statement"], "Manages keys")
        self.assertEqual(row["responsibility"], "shared", "statements on both sides imply shared")

    def test_unmatched_and_unrecognised_rows_are_reported_not_dropped(self):
        csv = "Control,Responsibility\nTC1.1,Provider\nZZ9.9,Provider\nTC1.2,Whoever\n".encode()
        out = mx.recognise("m.csv", csv, "Northwind", self.refs)
        self.assertEqual(out["summary"]["total"], 3)
        self.assertEqual(out["summary"]["unmatched"], 1)
        self.assertEqual(out["summary"]["unrecognised_responsibility"], 1)
        self.assertFalse(next(r for r in out["rows"] if r["ref"] == "ZZ9.9")["matched"])

    def test_prose_that_nobody_recognised_is_reported_not_guessed_around(self):
        csv = ("Requirement,Responsibility,Provider statement,Customer statement\n"
               "TC1.1,Whoever,Theirs,Ours\n"
               "TC1.2,AWS,Theirs,\n").encode()
        out = mx.recognise("m.csv", csv, "Amazon Web Services", self.refs)
        by = {r["ref"]: r for r in out["rows"]}
        self.assertIsNone(by["TC1.1"]["responsibility"], "statements must not override an unknown value")
        self.assertEqual(out["summary"]["unrecognised_responsibility"], 1)
        self.assertEqual(by["TC1.2"]["responsibility"], "provider", "the vendor's own name is the provider")

    def test_an_na_column_is_not_a_mark_column(self):
        csv = "Requirement,Provider statement,Customer\nTC1.1,We patch the platform,N/A\nTC1.2,All ours,N/A\n".encode()
        out = mx.recognise("m.csv", csv, "Northwind", self.refs)
        roles = {c["column"]: c["role"] for c in out["columns"]}
        self.assertEqual(roles["Customer"], "customer_statement")
        self.assertEqual({r["responsibility"] for r in out["rows"]}, {"provider"})

    def test_a_file_past_the_row_limit_says_so(self):
        from governance.risk_import import MAX_ROWS
        lines = ["Requirement,Responsibility"] + [f"X{i},Provider" for i in range(MAX_ROWS + 5)]
        out = mx.recognise("m.csv", "\n".join(lines).encode(), "Northwind", self.refs)
        self.assertTrue(out["summary"]["truncated"])
        self.assertEqual(out["summary"]["total"], MAX_ROWS)
        self.assertEqual(out["summary"]["row_limit"], MAX_ROWS)

    def test_parse_requires_a_framework(self):
        upload = SimpleUploadedFile("m.csv", b"Requirement,Responsibility\n6.1,Provider\n")
        r = self.c.post(f"/api/vendors/{self.v.pk}/matrix/parse/", {"file": upload})
        self.assertEqual(r.status_code, 400)
        self.assertIn("framework", r.data)

    def test_no_control_column_is_an_error_not_a_guess(self):
        out = mx.recognise("m.csv", b"Foo,Bar\n1,2\n", "Northwind", self.refs)
        self.assertEqual(out["rows"], [])
        self.assertIn("error", out["summary"])

    def test_xlsx_is_read_too(self):
        data = _xlsx([["Requirement", "Responsibility"], ["TC1.1", "Shared"]])
        out = mx.recognise("m.xlsx", data, "Northwind", self.refs)
        self.assertEqual(out["summary"]["matched"], 1)
        self.assertEqual(out["rows"][0]["responsibility"], "shared")

    def test_parse_then_confirm_end_to_end(self):
        upload = SimpleUploadedFile("northwind.csv",
                                    b"Requirement,Responsibility\nTC1.1,Provider\nTC1.2,Customer\n")
        r = self.c.post(f"/api/vendors/{self.v.pk}/matrix/parse/", {"file": upload, "framework": "tfw"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(SharedResponsibility.objects.count(), 0, "parse writes nothing")
        rows = [{"control": x["control_id"], "responsibility": x["responsibility"],
                 "provider_statement": x["provider_statement"],
                 "customer_statement": x["customer_statement"]} for x in r.data["rows"]]
        r = self.c.put(f"/api/vendors/{self.v.pk}/matrix/", {"rows": rows, "source": "import"},
                       format="json")
        self.assertEqual(r.data["saved"], 2)
        self.assertEqual(set(SharedResponsibility.objects.values_list("source", flat=True)), {"import"})

    def test_a_viewer_cannot_use_the_parser_as_an_oracle(self):
        upload = SimpleUploadedFile("m.csv", b"Requirement,Responsibility\nTC1.1,Provider\n")
        r = self.client_for(self.viewer).post(f"/api/vendors/{self.v.pk}/matrix/parse/", {"file": upload})
        self.assertEqual(r.status_code, 403)


# --------------------------------------------------------------------------- #
# RACI, readiness, risks, notifications
# --------------------------------------------------------------------------- #
class RaciTests(APITestBase):
    def test_exactly_one_accountable_per_control(self):
        c = self.client_for(self.manager)
        ok = c.post("/api/responsibilities/", {
            "control": self.tree.c1.pk, "user": self.owner.pk, "role": "accountable"}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        dup = c.post("/api/responsibilities/", {
            "control": self.tree.c1.pk, "user": self.manager.pk, "role": "accountable"}, format="json")
        self.assertEqual(dup.status_code, 400)
        self.assertIn("role", dup.data)

    def test_exactly_one_party(self):
        v = _vendor()
        c = self.client_for(self.manager)
        both = c.post("/api/responsibilities/", {
            "control": self.tree.c1.pk, "user": self.owner.pk, "vendor": v.pk, "role": "informed"},
            format="json")
        self.assertEqual(both.status_code, 400)
        neither = c.post("/api/responsibilities/", {"control": self.tree.c1.pk, "role": "informed"},
                         format="json")
        self.assertEqual(neither.status_code, 400)

    def test_patch_keeps_the_party_and_refuses_two_of_them(self):
        v = _vendor()
        c = self.client_for(self.manager)
        row = c.post("/api/responsibilities/", {
            "control": self.tree.c1.pk, "user": self.owner.pk, "role": "consulted"}, format="json").data
        r = c.patch(f"/api/responsibilities/{row['id']}/", {"note": "asked first"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["party_name"], self.owner.get_full_name())
        r = c.patch(f"/api/responsibilities/{row['id']}/", {"vendor": v.pk}, format="json")
        self.assertEqual(r.status_code, 400, "two parties is a refusal, not a database error")
        r = c.patch(f"/api/responsibilities/{row['id']}/", {"vendor": v.pk, "user": None}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["party_kind"], "vendor")

    def test_the_owner_is_the_implicit_accountable_and_gaps_are_counted(self):
        self.tree.c1.owner = self.owner
        self.tree.c1.save()
        r = self.client_for(self.viewer).get("/api/responsibilities/matrix/?framework=tfw")
        row = next(x for x in r.data["rows"] if x["control"] == self.tree.c1.pk)
        self.assertEqual(row["accountable"][0]["name"], self.owner.get_full_name())
        self.assertTrue(row["accountable"][0]["implicit"])
        self.assertEqual(r.data["gaps"], {"no_accountable": 1, "no_responsible": 2})

    def test_an_accountable_row_satisfies_the_readiness_owner_signal(self):
        Responsibility.objects.create(control=self.tree.c1, user=self.owner, role="accountable")
        control = scoring.annotate(Control.objects.filter(pk=self.tree.c1.pk), self.admin).get()
        owner = next(c for c in scoring.score_control(control, self.admin)["components"]
                     if c["key"] == "owner")
        self.assertEqual(owner["points"], 10)
        self.assertIn("responsibility matrix", owner["detail"])

    def test_matrix_export_is_csv(self):
        r = self.client_for(self.manager).get("/api/responsibilities/export/?framework=tfw")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Accountable", r.content.decode("utf-8").splitlines()[0])


class VendorRiskAndFeedTests(APITestBase):
    def test_a_risk_can_name_its_vendor(self):
        v = _vendor()
        r = self.client_for(self.manager).post("/api/risks/", {
            "title": "SOC report expired", "risk_type": "vendor", "vendor": v.pk,
            "likelihood": 3, "impact": 4}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["vendor_name"], "Northwind Cloud")
        self.assertEqual(self.client_for(self.manager).get(f"/api/vendors/{v.pk}/").data["open_risk_count"], 1)

    def test_onboarding_prompts_the_owner_and_managers_until_the_matrix_is_stated(self):
        v = _vendor(owner=self.owner)
        keys = {i["key"] for i in build_feed(self.owner)}
        self.assertIn(f"vendor-onboard:{v.pk}", keys)
        self.assertIn(f"vendor-onboard:{v.pk}", {i["key"] for i in build_feed(self.manager)})
        self.assertNotIn(f"vendor-onboard:{v.pk}", {i["key"] for i in build_feed(self.viewer)},
                         "a viewer who owns nothing is not prompted")
        SharedResponsibility.objects.create(vendor=v, control=self.tree.c1, responsibility="provider")
        self.assertNotIn(f"vendor-onboard:{v.pk}", {i["key"] for i in build_feed(self.owner)})

    def test_expiring_and_missing_assurance_surface_to_the_owner(self):
        v = _vendor(owner=self.owner, tier="critical")
        VendorAssessment.objects.create(vendor=v, kind="soc2_type2", result="satisfactory",
                                        expires_at=timezone.localdate() + timedelta(days=20))
        items = {i["key"]: i for i in build_feed(self.owner)}
        self.assertTrue(any(k.startswith("vendor-expiry:") for k in items))
        v2 = _vendor(name="Bare Critical", owner=self.owner, tier="critical")
        self.assertIn(f"vendor-assurance:{v2.pk}", {i["key"] for i in build_feed(self.owner)})
