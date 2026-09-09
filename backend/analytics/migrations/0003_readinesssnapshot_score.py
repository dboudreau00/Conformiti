from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_workspaces"),
    ]

    operations = [
        migrations.AddField(
            model_name="readinesssnapshot",
            name="score",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
