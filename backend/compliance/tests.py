"""Control library, evidence mapping RBAC and seed idempotence."""
from django.core.management import call_command

from compliance.models import Control, ControlEvidence, Framework
from documents.models import EDIT, VIEW, Folder
from testutils import APITestBase, grant, make_doc


class ControlApiTests(APITestBase):
    def test_controls_are_readable_by_everyone_but_only_managers_patch(self):
        c = self.client_for(self.viewer)
        self.assertEqual(c.get("/api/controls/").status_code, 200)
        self.assertEqual(c.get(f"/api/frameworks/{self.tree.framework.key}/controls/").status_code, 200)
        self.assertEqual(c.patch(f"/api/controls/{self.tree.c1.pk}/", {"status": "implemented"}, format="json").status_code, 403)
        m = self.client_for(self.manager)
        r = m.patch(f"/api/controls/{self.tree.c1.pk}/", {"status": "implemented", "owner": self.owner.pk}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["owner_name"], "Owen Tester")
        # the catalog itself is not writable through the API
        self.assertEqual(m.post("/api/controls/", {"control_id": "X"}, format="json").status_code, 405)
        self.assertEqual(m.delete(f"/api/controls/{self.tree.c1.pk}/").status_code, 405)
        # identifying fields are read-only
        m.patch(f"/api/controls/{self.tree.c1.pk}/", {"control_id": "HACK", "title": "x"}, format="json")
        self.assertEqual(Control.objects.get(pk=self.tree.c1.pk).control_id, "TC1.1")

    def test_framework_counts(self):
        r = self.client_for(self.viewer).get("/api/frameworks/")
        fw = r.data["results"][0]
        self.assertEqual(fw["control_count"], 2)
        self.assertEqual(fw["implemented_count"], 0)


class EvidenceMappingTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.doc = make_doc(self.tree.ctrl1, self.owner, name="ACP")

    def test_counts_respect_folder_visibility(self):
        ControlEvidence.objects.create(control=self.tree.c1, document=self.doc, linked_by=self.manager)
        vis = self.client_for(self.viewer).get(f"/api/controls/{self.tree.c1.pk}/").data
        self.assertEqual(vis["evidence_count"], 0)
        self.assertEqual(self.client_for(self.viewer).get("/api/control-evidence/").data["count"], 0)
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        vis = self.client_for(self.viewer).get(f"/api/controls/{self.tree.c1.pk}/").data
        self.assertEqual(vis["evidence_count"], 1)
        rows = self.client_for(self.viewer).get("/api/control-evidence/").data["results"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["can_unlink"])

    def test_link_requires_edit_or_framework_capability(self):
        payload = {"control": self.tree.c2.pk, "document": self.doc.pk, "note": "covers it"}
        # viewer can't even see the document
        self.assertEqual(self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json").status_code, 403)
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        self.assertEqual(self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json").status_code, 403)
        grant(self.tree.ctrl1, user=self.viewer, level=EDIT)
        r = self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["can_unlink"])
        self.assertEqual(ControlEvidence.objects.get(pk=r.data["id"]).linked_by, self.viewer)
        # duplicate link -> 400, not 500
        self.assertEqual(self.client_for(self.viewer).post("/api/control-evidence/", payload, format="json").status_code, 400)
        # an auditor is capped at view even with a manage grant: sees the link, cannot remove it
        grant(self.tree.ctrl1, user=self.auditor, level=EDIT)
        self.assertEqual(self.client_for(self.auditor).get(f"/api/control-evidence/{r.data['id']}/").status_code, 200)
        self.assertEqual(self.client_for(self.auditor).delete(f"/api/control-evidence/{r.data['id']}/").status_code, 403)
        self.assertEqual(self.client_for(self.manager).delete(f"/api/control-evidence/{r.data['id']}/").status_code, 204)
        # links are immutable
        self.assertEqual(self.client_for(self.manager).patch(f"/api/control-evidence/{r.data['id']}/", {"note": "x"}, format="json").status_code, 405)

    def test_bulk_attach_reports_skips(self):
        hidden = make_doc(self.tree.ctrl2, self.manager, name="hidden")
        grant(self.tree.ctrl1, user=self.owner, level=EDIT)
        ControlEvidence.objects.create(control=self.tree.c1, document=self.doc, linked_by=self.manager)
        r = self.client_for(self.owner).post("/api/control-evidence/bulk/", {
            "control": self.tree.c1.pk, "documents": [self.doc.pk, hidden.pk, 424242], "note": "audit prep",
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["created"], [])
        reasons = {s["document"]: s["reason"] for s in r.data["skipped"]}
        self.assertEqual(reasons[self.doc.pk], "already linked")
        self.assertEqual(reasons[hidden.pk], "not found or not visible")
        self.assertEqual(reasons[424242], "not found or not visible")
        r = self.client_for(self.owner).post("/api/control-evidence/bulk/", {"control": self.tree.c2.pk, "documents": [self.doc.pk]}, format="json")
        self.assertEqual(len(r.data["created"]), 1)
        self.assertEqual(self.client_for(self.owner).post("/api/control-evidence/bulk/", {"control": 0, "documents": [1]}, format="json").status_code, 400)

    def test_choices_only_lists_visible_documents(self):
        make_doc(self.tree.ctrl2, self.manager, name="Other")
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        data = self.client_for(self.viewer).get("/api/control-evidence/choices/").data
        self.assertEqual([d["name"] for d in data["documents"]], ["ACP"])
        self.assertEqual(len(data["controls"]), 2)


class SeedTests(APITestBase):
    def test_seed_frameworks_is_idempotent_and_matches_the_documented_counts(self):
        call_command("seed_frameworks", "--with-folders", verbosity=0)
        counts = {
            fw.key: Control.objects.filter(category__framework=fw).count()
            for fw in Framework.objects.exclude(key="tfw")
        }
        self.assertEqual(counts, {"soc2": 61, "iso27001": 93, "pci_dss_v4": 63})
        folders_before = Folder.objects.count()
        call_command("seed_frameworks", "--with-folders", verbosity=0)
        self.assertEqual(Folder.objects.count(), folders_before)
        self.assertEqual(sum(counts.values()), 217)
        # every control has exactly one folder, every folder root is flagged
        real = Folder.objects.filter(control__isnull=False).exclude(control__category__framework__key="tfw")
        self.assertEqual(real.count(), 217)
        self.assertEqual(Folder.objects.filter(is_framework_root=True).count(), 4)  # 3 real + the test one
        # the ISO root name no longer carries a path separator
        self.assertFalse(Folder.objects.filter(is_framework_root=True, name__contains="/").exists())
