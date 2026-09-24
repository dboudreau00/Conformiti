"""Controls come in their standard's order.

The register sorted control_id as text, so ISO 27001 read A.5.1, A.5.10 ...
A.5.19, A.5.2 and PCI DSS read 12.1, 12.10, 12.2. Each control now holds its
place in its framework's data file (Control.order), the way categories hold
theirs, and every list of controls sorts on it.
"""
import csv
import importlib
import io
import json
import os
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from compliance.management.commands.seed_frameworks import DATA_DIR, DATA_FILES
from compliance.models import Control, ControlCategory
from testutils import APITestBase

migration = importlib.import_module("compliance.migrations.0008_control_order")


def file_order():
    """{framework key: [control_id, ...]} in the order the data files list them."""
    order = {}
    for name in DATA_FILES:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            data = json.load(f)
        order[data["key"]] = [c["control_id"] for cat in data["categories"] for c in cat["controls"]]
    return order


class ControlOrderTests(APITestBase):
    def seed(self):
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())

    def register(self, framework_key):
        """The paged register for one framework, every page."""
        client = self.client_for(self.admin)
        ids, page = [], 1
        while True:
            r = client.get("/api/controls/", {"category__framework__key": framework_key, "page": page})
            self.assertEqual(r.status_code, 200, r.data)
            ids += [row["control_id"] for row in r.data["results"]]
            if not r.data["next"]:
                return ids
            page += 1

    def test_the_register_lists_every_shipped_framework_in_its_files_order(self):
        self.seed()
        for key, expected in file_order().items():
            with self.subTest(framework=key):
                self.assertEqual(self.register(key), expected)
                r = self.client_for(self.admin).get(f"/api/frameworks/{key}/controls/")
                self.assertEqual([row["control_id"] for row in r.data], expected)

    def test_clause_numbers_ascend_where_text_order_broke_them(self):
        self.seed()
        iso = self.register("iso27001")
        self.assertEqual([i for i in iso if i.startswith("A.5.")], [f"A.5.{n}" for n in range(1, 38)])
        pci = self.register("pci_dss_v4")
        self.assertEqual([i for i in pci if i.startswith("12.")], [f"12.{n}" for n in range(1, 11)])

    def test_the_csv_export_keeps_the_same_order(self):
        self.seed()
        r = self.client_for(self.admin).get("/api/controls/export/", {"category__framework__key": "iso27001"})
        self.assertEqual(r.status_code, 200)
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
        self.assertEqual([row[3] for row in rows[1:]], file_order()["iso27001"])

    def test_seeding_again_puts_a_scrambled_order_back(self):
        self.seed()
        for n, control in enumerate(Control.objects.filter(category__framework__key="iso27001")
                                    .order_by("-control_id")):
            Control.objects.filter(pk=control.pk).update(order=n + 1)
        self.assertNotEqual(self.register("iso27001"), file_order()["iso27001"])
        self.seed()
        self.assertEqual(self.register("iso27001"), file_order()["iso27001"])


class TiedCategoryTests(APITestBase):
    """Two categories may share an order (the admin can set any). Places
    restart at 1 in each, so every list must break the tie on the category
    before the place, or the two interleave: AA-1, BB-1, AA-2."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from compliance.models import Framework
        from vendors.models import Vendor

        tie = Framework.objects.create(key="tie", name="Tie", version="1")
        for key in ("AA", "BB"):
            category = ControlCategory.objects.create(framework=tie, key=key, name=key, order=0)
            for n in (1, 2):
                Control.objects.create(category=category, control_id=f"{key}-{n}", title=f"{key}-{n}")
        cls.vendor = Vendor.objects.create(name="Tie Hosting")

    GROUPED = ["AA-1", "AA-2", "BB-1", "BB-2"]

    def test_every_control_list_keeps_tied_categories_grouped(self):
        client = self.client_for(self.admin)
        r = client.get("/api/controls/", {"category__framework__key": "tie"})
        self.assertEqual([row["control_id"] for row in r.data["results"]], self.GROUPED)
        r = client.get("/api/controls/export/", {"category__framework__key": "tie"})
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8"))))
        self.assertEqual([row[3] for row in rows[1:]], self.GROUPED)
        r = client.get("/api/control-evidence/choices/")
        self.assertEqual([c["label"] for c in r.data["controls"] if c["framework"] == "tie"], self.GROUPED)
        r = client.get("/api/responsibilities/matrix/", {"framework": "tie"})
        self.assertEqual([row["control_id"] for row in r.data["rows"]], self.GROUPED)
        r = client.get(f"/api/vendors/{self.vendor.pk}/matrix/", {"framework": "tie"})
        self.assertEqual([row["control_id"] for row in r.data["rows"]], self.GROUPED)


class ControlPlacementTests(APITestBase):
    """Controls a seeder creates without a place go last in their category,
    in the order they were created."""

    def test_the_fixture_controls_were_placed_in_creation_order(self):
        self.assertEqual((self.tree.c1.order, self.tree.c2.order), (1, 2))

    def test_a_new_control_without_a_place_goes_last(self):
        c = Control.objects.create(category=self.tree.category, control_id="TC1.10", title="Tenth")
        self.assertEqual(c.order, 3)
        self.assertEqual(list(self.tree.category.controls.values_list("control_id", flat=True)),
                         ["TC1.1", "TC1.2", "TC1.10"])

    def test_a_given_place_is_kept(self):
        c = Control.objects.create(category=self.tree.category, control_id="TC1.0", title="Zeroth", order=1)
        self.assertEqual(c.order, 1)
        c.refresh_from_db()
        self.assertEqual(c.order, 1)

    def other_category(self):
        return ControlCategory.objects.create(framework=self.tree.framework, key="TD", name="TD", order=1)

    def test_a_control_moved_to_another_category_goes_last_there(self):
        other = self.other_category()
        Control.objects.create(category=other, control_id="TD1.1", title="Already there")
        c = Control.objects.get(pk=self.tree.c1.pk)
        c.category = other
        c.save(update_fields=["category", "title"])
        c.refresh_from_db()
        self.assertEqual((c.category_id, c.order), (other.pk, 2))

    def test_a_full_save_after_a_move_places_it_too(self):
        other = self.other_category()
        c = Control.objects.get(pk=self.tree.c2.pk)
        c.category = other
        c.save()
        c.refresh_from_db()
        self.assertEqual((c.category_id, c.order), (other.pk, 1))

    def test_a_move_with_a_place_keeps_the_place(self):
        other = self.other_category()
        c = Control.objects.get(pk=self.tree.c2.pk)
        c.category, c.order = other, 7
        c.save(update_fields=["category", "order"])
        c.refresh_from_db()
        self.assertEqual((c.category_id, c.order), (other.pk, 7))

    def test_a_move_is_seen_after_a_partial_load_or_refresh(self):
        """The stored place is read from the row, so a deferred field or a
        partial refresh cannot hide a move."""
        other = self.other_category()
        Control.objects.create(category=other, control_id="TD1.1", title="Already there")
        c = Control.objects.only("id", "control_id", "title").get(pk=self.tree.c1.pk)
        c.category = other
        c.save()
        c.refresh_from_db()
        self.assertEqual((c.category_id, c.order), (other.pk, 2))

        c = Control.objects.get(pk=self.tree.c2.pk)
        c.category = other
        c.refresh_from_db(fields=["title"])
        c.save(update_fields=(f for f in ["category", "title"]))
        c.refresh_from_db()
        self.assertEqual((c.category_id, c.order), (other.pk, 3))

    def test_saves_that_do_not_move_it_leave_the_place_alone(self):
        c = Control.objects.get(pk=self.tree.c1.pk)
        c.title = "Renamed"
        c.save()
        c.status = Control.Status.IMPLEMENTED
        c.save(update_fields=["status"])
        c.refresh_from_db()
        self.assertEqual(c.order, 1)


class PlaceControlsMigrationTests(APITestBase):
    """compliance 0008 places the rows an existing installation already has."""

    def run_migration(self):
        state = MigrationExecutor(connection).loader.project_state(("compliance", "0008_control_order"))

        class Editor:
            pass

        editor = Editor()
        editor.connection = connection
        migration.place_controls(state.apps, editor)

    def test_existing_rows_are_placed_from_the_files_then_by_creation(self):
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())
        a5 = ControlCategory.objects.get(framework__key="iso27001", key="A5")
        # A control the files do not list, in a shipped category.
        Control.objects.create(category=a5, control_id="A.5.0-local", title="Local")
        Control.objects.update(order=0)

        self.run_migration()

        expected = file_order()
        iso = list(Control.objects.filter(category__framework__key="iso27001")
                   .values_list("control_id", flat=True))
        self.assertEqual(iso[:37], expected["iso27001"][:37])
        self.assertEqual(iso[37], "A.5.0-local")
        self.assertEqual(Control.objects.get(control_id="A.5.0-local").order, 38)
        for key in ("soc2", "pci_dss_v4"):
            self.assertEqual(list(Control.objects.filter(category__framework__key=key)
                                  .values_list("control_id", flat=True)), expected[key])
        # Not a shipped framework: creation order.
        self.assertEqual(list(self.tree.category.controls.values_list("control_id", "order")),
                         [("TC1.1", 1), ("TC1.2", 2)])
        self.assertFalse(Control.objects.filter(order=0).exists())

    def test_a_listed_control_missing_from_its_category_leaves_a_gap_not_a_tie(self):
        """Listed controls take their file place, so the next seed changes
        nothing and a control the file does not list stays last."""
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())
        a5 = ControlCategory.objects.get(framework__key="iso27001", key="A5")
        a6 = ControlCategory.objects.get(framework__key="iso27001", key="A6")
        Control.objects.create(category=a5, control_id="A.5.0-local", title="Local")
        Control.objects.filter(category__framework__key="iso27001", control_id="A.5.2").update(category=a6)
        Control.objects.update(order=0)

        self.run_migration()

        places = dict(a5.controls.values_list("control_id", "order"))
        self.assertEqual((places["A.5.1"], places["A.5.3"], places["A.5.37"]), (1, 3, 37))
        self.assertEqual(places["A.5.0-local"], 38)
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())
        ids = list(a5.controls.values_list("control_id", flat=True))
        self.assertEqual(ids, file_order()["iso27001"][:37] + ["A.5.0-local"])

    def test_seeding_keeps_a_control_the_file_does_not_list_last(self):
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())
        a5 = ControlCategory.objects.get(framework__key="iso27001", key="A5")
        Control.objects.create(category=a5, control_id="A.5.0-local", title="Local", order=1)
        call_command("seed_frameworks", verbosity=0, stdout=StringIO())
        self.assertEqual(list(a5.controls.values_list("control_id", flat=True))[-2:],
                         ["A.5.37", "A.5.0-local"])
        self.assertEqual(Control.objects.get(control_id="A.5.0-local").order, 38)
