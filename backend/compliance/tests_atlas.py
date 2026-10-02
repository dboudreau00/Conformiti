"""The coverage atlas: every control in one response, with the crosswalk beside
it, for the dashboard. Read-only, so the questions are who may read it, whose
rows it holds, and what it costs."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts import tenancy
from accounts import tests_tenancy
from compliance.models import Control, ControlCategory, ControlEvidence, ControlMapping, Framework
from compliance.tests_control_order import file_order
from documents.models import VIEW
from testutils import APITestBase, grant, make_doc

ATLAS = "/api/controls/atlas/"


class AtlasTests(APITestBase):
    def atlas(self, user=None, **kwargs):
        r = self.client_for(user or self.admin).get(ATLAS, **kwargs)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def seed(self):
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())

    def test_the_shape(self):
        data = self.atlas()
        self.assertEqual(set(data), {"frameworks", "controls", "themes"})
        fw = data["frameworks"][0]
        self.assertEqual(set(fw), {"id", "key", "name", "version", "categories"})
        self.assertEqual(fw["key"], "tfw")
        self.assertEqual(fw["categories"], [{"id": self.tree.category.pk, "key": "TC", "name": "TC - Test Category"}])
        self.assertEqual(
            [set(c) for c in data["controls"]],
            [{"id", "ref", "title", "category", "status", "score", "band"}] * 2,
        )
        first = data["controls"][0]
        self.assertEqual((first["id"], first["ref"], first["category"]),
                         (self.tree.c1.pk, "TC1.1", self.tree.category.pk))

    def test_every_shipped_control_comes_in_its_standards_order_and_every_theme_member_is_one(self):
        self.seed()
        data = self.atlas()
        framework_of = {cat["id"]: fw["key"] for fw in data["frameworks"] for cat in fw["categories"]}
        refs = {}
        for c in data["controls"]:
            refs.setdefault(framework_of[c["category"]], []).append(c["ref"])
        expected = file_order()
        for key, order in expected.items():
            with self.subTest(framework=key):
                self.assertEqual(refs[key], order)
        self.assertEqual(sum(len(v) for v in expected.values()), 217)
        self.assertEqual(len(data["controls"]), 217 + 2, "the three standards and the test framework's two")

        names = [fw["name"] for fw in data["frameworks"]]
        self.assertEqual(names, sorted(names), "territories come in the schedule's order")

        ids = {c["id"] for c in data["controls"]}
        self.assertEqual(len(ids), len(data["controls"]))
        self.assertEqual(len(data["themes"]), ControlMapping.objects.count())
        self.assertEqual(len(data["themes"]), 20)
        for theme in data["themes"]:
            self.assertGreater(len(theme["controls"]), 1, theme["theme"])
            self.assertLessEqual(set(theme["controls"]), ids)

    def test_the_same_control_id_in_two_frameworks_stays_two_controls(self):
        other = Framework.objects.create(key="other", name="Other", version="1")
        cat = ControlCategory.objects.create(framework=other, key="OC", name="OC", order=0)
        twin = Control.objects.create(category=cat, control_id="TC1.1", title="Same ref, other standard")
        data = self.atlas()
        twins = [c for c in data["controls"] if c["ref"] == "TC1.1"]
        self.assertEqual({c["id"] for c in twins}, {self.tree.c1.pk, twin.pk})
        self.assertEqual({c["category"] for c in twins}, {self.tree.category.pk, cat.pk})
        self.assertEqual([fw["key"] for fw in data["frameworks"]], ["other", "tfw"])

    def test_the_roles_that_read_the_register_read_the_atlas_and_an_auditor_does_not(self):
        self.assertEqual(self.client_for().get(ATLAS).status_code, 401)
        self.assertEqual(self.client_for(self.auditor).get(ATLAS).status_code, 403)
        for user in (self.viewer, self.owner, self.manager, self.admin):
            with self.subTest(user=user.username):
                self.assertEqual(self.client_for(user).get(ATLAS).status_code, 200)

    def test_it_only_reads(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                r = getattr(self.client_for(self.admin), method)(ATLAS, {}, format="json")
                self.assertIn(r.status_code, (404, 405))

    def test_not_applicable_controls_are_unscored(self):
        Control.objects.filter(pk=self.tree.c2.pk).update(status="not_applicable")
        rows = {c["id"]: c for c in self.atlas()["controls"]}
        self.assertEqual(rows[self.tree.c2.pk]["status"], "not_applicable")
        self.assertIsNone(rows[self.tree.c2.pk]["score"])
        self.assertEqual(rows[self.tree.c2.pk]["band"], "not_applicable")
        self.assertIsNotNone(rows[self.tree.c1.pk]["score"])

    def test_the_score_is_the_callers_not_the_organisations(self):
        """Hidden evidence must not show up in a score: an org-wide integer per
        control tells a folder-restricted reader whether it exists."""
        c1 = self.tree.c1
        Control.objects.filter(pk=c1.pk).update(
            status="implemented", owner=self.owner, last_tested_on=timezone.localdate() - timedelta(days=10))
        doc = make_doc(self.tree.ctrl1, self.owner, name="Policy", days=90)
        ControlEvidence.objects.create(control=c1, document=doc, linked_by=self.manager)

        def mine(user):
            row = next(c for c in self.atlas(user)["controls"] if c["id"] == c1.pk)
            register = self.client_for(user).get(f"/api/controls/{c1.pk}/").data
            self.assertEqual((row["score"], row["band"]), (register["readiness_score"], register["readiness_band"]))
            return row["score"]

        self.assertEqual(mine(self.admin), 100)
        # val holds no folder grant, so the evidence behind the score is not hers to count.
        self.assertEqual(mine(self.viewer), 60)

    def test_the_cost_is_fixed_whatever_the_number_of_controls(self):
        mapping = ControlMapping.objects.create(theme="Access control")
        mapping.controls.add(self.tree.c1, self.tree.c2)
        manager, viewer = self.client_for(self.manager), self.client_for(self.viewer)
        grant(self.tree.ctrl1, user=self.viewer, level=VIEW)
        # Categories, the folders the caller may see, the controls, the mapping.
        with self.assertNumQueries(4):
            manager.get(ATLAS)
        with CaptureQueriesContext(connection) as before:
            viewer.get(ATLAS)
        for n in range(10):
            control = Control.objects.create(
                category=self.tree.category, control_id=f"TC9.{n}", title=f"Extra {n}")
            mapping.controls.add(control)
        with self.assertNumQueries(4):
            r = manager.get(ATLAS)
        with CaptureQueriesContext(connection) as after:
            viewer.get(ATLAS)
        self.assertEqual(len(after), len(before), "a folder-restricted caller pays the same however many controls")
        self.assertEqual(len(r.data["controls"]), 12)
        self.assertEqual(len(r.data["themes"][0]["controls"]), 12)

    def test_a_theme_that_joins_one_control_is_not_a_theme_for_the_atlas(self):
        ControlMapping.objects.create(theme="Alone").controls.add(self.tree.c1)
        ControlMapping.objects.create(theme="Empty")
        self.assertEqual(self.atlas()["themes"], [])

    def test_theme_members_follow_the_register(self):
        mapping = ControlMapping.objects.create(theme="Access control")
        mapping.controls.add(self.tree.c2, self.tree.c1)
        self.assertEqual(self.atlas()["themes"][0]["controls"], [self.tree.c1.pk, self.tree.c2.pk])


class AtlasTenancyTests(tests_tenancy.TwoWorkspaces):
    def test_another_workspaces_controls_categories_and_themes_never_appear(self):
        with tenancy.scoped(self.beta):
            beta_theme = ControlMapping.objects.create(theme="Beta theme")
            beta_theme.controls.add(self.b_tree.c1, self.b_tree.c2)
        data = self.client_for(self.manager).get(ATLAS).data
        self.assertEqual({c["id"] for c in data["controls"]}, {self.tree.c1.pk, self.tree.c2.pk})
        self.assertEqual([fw["id"] for fw in data["frameworks"]], [self.tree.framework.pk])
        self.assertEqual(
            {cat["id"] for fw in data["frameworks"] for cat in fw["categories"]}, {self.tree.category.pk})
        self.assertEqual(data["themes"], [])

        beta = self.client_for(self.b_manager).get(ATLAS).data
        self.assertEqual({c["id"] for c in beta["controls"]}, {self.b_tree.c1.pk, self.b_tree.c2.pk})
        self.assertEqual([t["theme"] for t in beta["themes"]], ["Beta theme"])

    def test_a_join_row_that_crosses_the_line_is_dropped_not_followed(self):
        """The join table behind a many-to-many is not scoped to a workspace.
        A row that links an Alpha theme to a Beta control must neither leak
        the Beta control nor make a theme of one."""
        theme = ControlMapping.objects.create(theme="Alpha theme")
        theme.controls.add(self.tree.c1)
        with tenancy.unscoped():
            ControlMapping.controls.through.objects.create(
                controlmapping_id=theme.pk, control_id=self.b_tree.c1.pk)
        data = self.client_for(self.manager).get(ATLAS).data
        self.assertEqual(data["themes"], [])
        self.assertNotIn(self.b_tree.c1.pk, {c["id"] for c in data["controls"]})
        self.assertNotIn(str(self.b_tree.c1.pk), str(data["themes"]))

    def test_both_workspaces_own_a_framework_called_tfw_and_each_atlas_holds_only_its_own(self):
        a = self.client_for(self.manager).get(ATLAS).data
        b = self.client_for(self.b_manager).get(ATLAS).data
        self.assertEqual([f["key"] for f in a["frameworks"]], ["tfw"])
        self.assertEqual([f["key"] for f in b["frameworks"]], ["tfw"])
        self.assertNotEqual(a["frameworks"][0]["id"], b["frameworks"][0]["id"])
        self.assertFalse({c["id"] for c in a["controls"]} & {c["id"] for c in b["controls"]})
