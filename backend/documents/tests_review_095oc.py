import io
import time
import zipfile

from django.test import SimpleTestCase

from documents.models import MAX_FOLDER_DEPTH, Folder
from documents.preview import MAX_SHEET_COLS, _col_index, render_xlsx
from testutils import APITestBase, make_doc


def _xlsx(body):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>'
                                       '<sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>')
    return buf.getvalue()


class PreviewColumnReferenceTests(SimpleTestCase):
    def test_ordinary_references_still_resolve(self):
        self.assertEqual([_col_index(ref) for ref in ("A1", "Z9", "AA1", "XFD7")], [0, 25, 26, 16383])

    def test_a_long_run_of_letters_is_out_of_range_and_costs_nothing(self):
        started = time.monotonic()
        index = _col_index("A" * 400_000 + "1")
        self.assertGreaterEqual(index, MAX_SHEET_COLS)
        # The old cost was minutes; a generous bound keeps a slow runner from failing it.
        self.assertLess(time.monotonic() - started, 10.0)

    def test_a_sheet_carrying_one_still_renders_its_other_cells(self):
        body = ('<row r="1"><c r="A1" t="inlineStr"><is><t>kept</t></is></c>'
                f'<c r="{"A" * 300_000}1" t="inlineStr"><is><t>dropped</t></is></c></row>')
        started = time.monotonic()
        rendered = str(render_xlsx(_xlsx(body)))
        self.assertLess(time.monotonic() - started, 10.0)
        self.assertIn("kept", rendered)
        self.assertNotIn("dropped", rendered)


class FolderDepthTests(APITestBase):
    @staticmethod
    def _chain(levels, parent=None):
        for i in range(levels):
            parent = Folder.objects.create(name=f"D{i}", parent=parent)
        return parent

    def test_a_folder_cannot_be_made_below_the_ceiling(self):
        leaf = self._chain(MAX_FOLDER_DEPTH + 1)
        self.assertEqual(leaf.chain_length(), MAX_FOLDER_DEPTH)
        manager = self.client_for(self.manager)
        before = Folder.objects.count()
        refused = manager.post("/api/folders/", {"name": "One too deep", "parent": leaf.pk}, format="json")
        self.assertEqual(refused.status_code, 400, refused.data)
        self.assertIn("parent", refused.data)
        self.assertEqual(Folder.objects.count(), before)
        sibling = manager.post("/api/folders/", {"name": "Still allowed", "parent": leaf.parent_id}, format="json")
        self.assertEqual(sibling.status_code, 201, sibling.data)

    def test_a_move_that_pushes_a_subtree_past_the_ceiling_is_refused(self):
        deep = self._chain(MAX_FOLDER_DEPTH - 1)
        branch = Folder.objects.create(name="Branch")
        child = Folder.objects.create(name="Child", parent=branch)
        grand = Folder.objects.create(name="Grand", parent=child)
        manager = self.client_for(self.manager)
        refused = manager.patch(f"/api/folders/{branch.pk}/", {"parent": deep.pk}, format="json")
        self.assertEqual(refused.status_code, 400, refused.data)
        branch.refresh_from_db()
        self.assertIsNone(branch.parent_id)
        moved = manager.patch(f"/api/folders/{grand.pk}/", {"parent": deep.pk}, format="json")
        self.assertEqual(moved.status_code, 200, moved.data)

    def test_resending_the_same_parent_is_not_a_move(self):
        leaf = self._chain(MAX_FOLDER_DEPTH + 1)
        renamed = self.client_for(self.manager).patch(
            f"/api/folders/{leaf.pk}/", {"name": "Renamed", "parent": leaf.parent_id}, format="json")
        self.assertEqual(renamed.status_code, 200, renamed.data)

    def test_a_chain_made_before_the_guard_does_not_break_the_folder_views(self):
        leaf = self._chain(MAX_FOLDER_DEPTH + 4)
        self.assertIsNone(leaf.chain_length())
        admin = self.client_for(self.admin)
        detail = admin.get(f"/api/folders/{leaf.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["path"], leaf.name)
        self.assertEqual(admin.get("/api/folders/").status_code, 200)
        make_doc(leaf, self.manager, name="Filed deep")
