"""Controls get a place in their category, so the register reads in the
standard's own order (A.5.2 before A.5.10) instead of control_id as text.

Existing rows are placed from the framework data files this release ships
(matched by framework key, category key and control_id), at their place in
the file. A control those files do not list (another framework's, or one
added by hand) goes after the file's last place, in the order it was
created, which is the order its seeder read its own file.
``seed_frameworks`` keeps the shipped frameworks' places in step from then
on.
"""
import json
from collections import defaultdict
from pathlib import Path

from django.db import migrations, models

# Frozen here rather than imported: a migration must not change meaning when
# the seed command does. A file that is missing or unreadable places nothing.
DATA_FILES = ("soc2.json", "iso27001.json", "pci_dss_v4.json")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def shipped_places():
    """{(framework key, category key): {control_id: place}} from the data files."""
    places = {}
    for name in DATA_FILES:
        try:
            data = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for category in data.get("categories", []):
            places[(data["key"], category["key"])] = {
                control["control_id"]: n
                for n, control in enumerate(category.get("controls", []), start=1)
            }
    return places


def place_controls(apps, schema_editor):
    Control = apps.get_model("compliance", "Control")
    db = schema_editor.connection.alias
    places = shipped_places()
    by_category = defaultdict(list)
    rows = (Control.objects.using(db)
            .select_related("category__framework")
            .only("pk", "control_id", "order", "category__key", "category__framework__key")
            .order_by("pk"))
    for control in rows.iterator(chunk_size=1000):
        by_category[control.category_id].append(control)

    changed = []
    for controls in by_category.values():
        category = controls[0].category
        known = places.get((category.framework.key, category.key), {})
        # Listed controls take their place in the file, which is what
        # seed_frameworks writes, so its next run changes nothing even when
        # one of them is missing here. The rest follow the file's last place,
        # by creation.
        rest = sorted((c for c in controls if c.control_id not in known), key=lambda c: c.pk)
        for control in controls:
            if control.control_id in known:
                control.order = known[control.control_id]
        for n, control in enumerate(rest, start=len(known) + 1):
            control.order = n
        changed += controls
    Control.objects.using(db).bulk_update(changed, ["order"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("compliance", "0007_controlcategory_verbose_name_plural"),
    ]

    operations = [
        migrations.AddField(
            model_name="control",
            name="order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name="control",
            options={"ordering": ["category", "order", "control_id"]},
        ),
        migrations.RunPython(place_controls, migrations.RunPython.noop),
    ]
