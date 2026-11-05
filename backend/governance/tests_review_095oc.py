import io
import zipfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from accounts import tenancy
from accounts.models import User, Workspace
from governance import views as governance_views
from governance.models import AccessReview, AccessReviewItem, Risk
from governance.risk_import import normalize, parse_upload
from testutils import APITestBase, make_roles, make_user, make_xlsx


def upload(client, name, data):
    return client.post("/api/risks/import/", {"file": SimpleUploadedFile(name, data)}, format="multipart")


class StaleItemSaveTests(APITestBase):
    """PRG-03: a save must not write back the decision a concurrent request already changed."""

    def setUp(self):
        super().setUp()
        self.admin_client = self.client_for(self.admin)
        self.review_id = self.admin_client.post("/api/access-reviews/", {"name": "Q"}, format="json").data["id"]
        self.item = AccessReviewItem.objects.get(review_id=self.review_id, username="val")

    def test_a_notes_only_patch_that_loaded_the_row_before_a_decision_keeps_the_decision(self):
        stale = AccessReviewItem.objects.get(pk=self.item.pk)
        self.admin_client.patch(f"/api/access-review-items/{self.item.pk}/", {"decision": "revoke"}, format="json")
        with mock.patch.object(governance_views.AccessReviewItemViewSet, "get_object", return_value=stale):
            r = self.admin_client.patch(
                f"/api/access-review-items/{self.item.pk}/", {"decision_notes": "matches the ticket"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["decision"], "revoke")
        self.item.refresh_from_db()
        self.assertEqual(self.item.decision, "revoke")
        self.assertEqual(self.item.decision_notes, "matches the ticket")
        self.assertEqual(self.item.decided_by_id, self.admin.pk)
        self.assertIsNotNone(self.item.decided_at)

    def test_an_older_review_edit_does_not_put_back_an_older_name(self):
        stale = AccessReview.objects.get(pk=self.review_id)
        self.admin_client.patch(f"/api/access-reviews/{self.review_id}/", {"name": "Renamed"}, format="json")
        with mock.patch.object(governance_views.AccessReviewViewSet, "get_object", return_value=stale):
            r = self.admin_client.patch(f"/api/access-reviews/{self.review_id}/", {"notes": "added"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        review = AccessReview.objects.get(pk=self.review_id)
        self.assertEqual((review.name, review.notes), ("Renamed", "added"))

    def test_an_auditor_cannot_change_an_item_or_a_review(self):
        auditor = self.client_for(self.auditor)
        r = auditor.patch(f"/api/access-review-items/{self.item.pk}/", {"decision": "keep"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = auditor.patch(f"/api/access-reviews/{self.review_id}/", {"name": "x"}, format="json")
        self.assertEqual(r.status_code, 403)


class LastAdministratorTests(APITestBase):
    """PRG-04: an access review never deactivates the last administrator, as the user API refuses to."""

    def review_other_workspace(self, revoke):
        """A superuser whose home is Default reviews workspace Beta: ``revoke`` (usernames) go, the rest are kept."""
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta")
        with tenancy.scoped(beta):
            roles = make_roles()
            admins = [make_user(name, roles["Administrator"]) for name in ("bea", "bex")]
            viewer = make_user("bev", roles["Viewer"])
        client = self.client_for(self.admin)
        client.defaults["HTTP_X_WORKSPACE"] = "beta"
        r = client.post("/api/access-reviews/", {"name": "Q"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rid = r.data["id"]
        for item in client.get(f"/api/access-review-items/?review={rid}").data:
            decision = "revoke" if item["username"] in revoke else "keep"
            self.assertEqual(
                client.patch(f"/api/access-review-items/{item['id']}/", {"decision": decision}, format="json")
                .status_code, 200)
        r = client.post(f"/api/access-reviews/{rid}/complete/")
        self.assertEqual(r.status_code, 200, r.data)
        return beta, admins, viewer, r.data["applied"]

    def active(self, beta, username):
        with tenancy.scoped(beta):
            return User.objects.get(username=username).is_active

    def test_the_second_of_two_administrators_marked_revoke_is_kept(self):
        beta, _, _, applied = self.review_other_workspace({"bea", "bex"})
        self.assertEqual(len(applied["revoked"]), 1)
        self.assertEqual(len(applied["skipped"]), 1)
        self.assertEqual(applied["skipped"][0]["reason"], "this is the last active administrator")
        self.assertEqual(sum(self.active(beta, n) for n in ("bea", "bex")), 1)

    def test_completing_locks_the_administrators_before_it_checks(self):
        # The user API's removals take this lock too, so the two are taken in turn on PostgreSQL. SQLite takes no row
        # locks, so what is checked is that the lock is asked for.
        from django.db.models.query import QuerySet

        seen = []
        original = QuerySet.select_for_update

        def record(queryset, *args, **kwargs):
            seen.append((queryset.model.__name__, kwargs))
            return original(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "select_for_update", record):
            self.review_other_workspace({"bea", "bex"})
        self.assertIn(("User", {"of": ("self",)}), seen)

    def test_an_ordinary_account_is_still_revoked_beside_the_administrators(self):
        beta, _, _, applied = self.review_other_workspace({"bev"})
        self.assertEqual(applied["revoked"], ["bev"])
        self.assertFalse(self.active(beta, "bev"))
        self.assertTrue(self.active(beta, "bea") and self.active(beta, "bex"))


class RiskImportTests(APITestBase):
    """PRG-05, PRG-06, PRG-07, PRG-10, ROB-12."""

    def test_two_people_with_one_name_are_not_picked_between(self):  # PRG-05
        make_user("jane.a", self.roles["Viewer"], first_name="Jane", last_name="Doe")
        make_user("jane.b", self.roles["Viewer"], first_name="Jane", last_name="Doe")
        csv_bytes = b"Title,Owner\nShared name risk,Jane Doe\nLogin risk,jane.b\nUnique name risk,Owen Tester\n"
        r = upload(self.client_for(self.manager), "r.csv", csv_bytes)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(Risk.objects.get(title="Shared name risk").owner)
        self.assertEqual(Risk.objects.get(title="Login risk").owner.username, "jane.b")
        self.assertEqual(Risk.objects.get(title="Unique name risk").owner, self.owner)
        messages = [w["message"] for w in r.data["warnings"] if w["field"] == "owner"]
        self.assertEqual(len(messages), 1)
        self.assertIn("more than one person", messages[0])

    def test_a_date_valid_in_both_orders_is_reported(self):  # PRG-06
        rows = [["Title", "Due date"], ["Ambiguous", "05/06/2026"], ["Clear", "31/12/2026"], ["Same", "06/06/2026"]]
        records, issues, fatal = normalize(rows)
        self.assertIsNone(fatal)
        self.assertEqual(records[0]["due_date"].isoformat(), "2026-05-06")  # month first, as before
        self.assertEqual(records[1]["due_date"].isoformat(), "2026-12-31")
        self.assertEqual(records[2]["due_date"].isoformat(), "2026-06-06")
        self.assertEqual([i["row"] for i in issues], [2])
        self.assertIn("month/day", issues[0]["message"])

    def test_a_windows_1252_csv_is_read_and_says_so(self):  # PRG-07
        data = "Title,Description\nRésumé risk,café\n".encode("cp1252")
        r = upload(self.client_for(self.manager), "r.csv", data)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Risk.objects.get(title="Résumé risk").description, "café")
        self.assertTrue(any("windows-1252" in w["message"] for w in r.data["warnings"]))

    def test_a_utf8_csv_has_no_encoding_warning(self):  # PRG-07
        r = upload(self.client_for(self.manager), "r.csv", "Title\nRésumé risk\n".encode("utf-8"))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["warnings"], [])
        self.assertTrue(Risk.objects.filter(title="Résumé risk").exists())

    def test_a_csv_in_no_known_encoding_is_refused(self):  # PRG-07
        r = upload(self.client_for(self.manager), "r.csv", b"Title\nbad \x81 byte\n")
        self.assertEqual(r.status_code, 400)
        self.assertIn("UTF-8", str(r.data))
        self.assertFalse(Risk.objects.exists())

    def test_the_first_sheet_of_the_workbook_is_read_not_the_first_file(self):  # PRG-10
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

        def sheet(rows):
            body = "".join(
                f'<row r="{n}">' + "".join(
                    f'<c r="{chr(65 + c)}{n}" t="inlineStr"><is><t>{v}</t></is></c>' for c, v in enumerate(row))
                + "</row>" for n, row in enumerate(rows, start=1))
            return f'<worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>'

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
                        '<sheet name="Register" sheetId="2" r:id="rId9"/><sheet name="Cover" sheetId="1" r:id="rId1"/>'
                        '</sheets></workbook>')
            zf.writestr("xl/_rels/workbook.xml.rels",
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
                        '<Relationship Id="rId9" Type="x" Target="/xl/worksheets/sheet10.xml"/></Relationships>')
            zf.writestr("xl/worksheets/sheet1.xml", sheet([["Instructions", "Notes"]]))
            zf.writestr("xl/worksheets/sheet10.xml", sheet([["Title", "Status"], ["Sheet ten risk", "open"]]))
        r = upload(self.client_for(self.manager), "r.xlsx", buf.getvalue())
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 1)
        self.assertTrue(Risk.objects.filter(title="Sheet ten risk").exists())

    def test_a_package_without_a_workbook_part_reads_the_lowest_numbered_sheet(self):  # PRG-10
        buf = io.BytesIO()
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        with zipfile.ZipFile(buf, "w") as zf:
            for n, title in ((10, "ten"), (2, "two")):
                zf.writestr(f"xl/worksheets/sheet{n}.xml",
                            f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>{title}'
                            "</t></is></c></row></sheetData></worksheet>")
        self.assertEqual(parse_upload("r.xlsx", buf.getvalue()), [["two"]])

    def test_a_single_sheet_workbook_still_imports(self):  # PRG-10
        r = upload(self.client_for(self.manager), "r.xlsx", make_xlsx([["Title"], ["Plain risk"]]))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 1)

    def test_an_import_skips_a_title_that_landed_while_it_waited_for_the_lock(self):  # ROB-12
        # Stands in for the other import committing first: the title appears as the lock is taken. (On the unfixed
        # code this fails because the lock helper does not exist.)
        def winner_commits():
            Risk.objects.create(title="Laptop disk encryption gaps", created_by=self.manager)

        with mock.patch.object(governance_views, "_lock_workspace", side_effect=winner_commits) as lock:
            r = upload(self.client_for(self.manager), "r.csv", b"Title\nLaptop disk encryption gaps\n")
        lock.assert_called_once()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["created"], 0)
        self.assertEqual(len(r.data["skipped"]), 1)
        self.assertEqual(Risk.objects.filter(title="Laptop disk encryption gaps").count(), 1)

    def test_an_auditor_cannot_import(self):
        r = upload(self.client_for(self.auditor), "r.csv", b"Title\nx\n")
        self.assertEqual(r.status_code, 403)
