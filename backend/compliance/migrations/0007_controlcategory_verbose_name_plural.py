"""The admin listed ControlCategory as "Control categorys". Options only: no
schema change."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("compliance", "0006_workspaces"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="controlcategory",
            options={"ordering": ["framework", "order", "key"], "verbose_name_plural": "control categories"},
        ),
    ]
