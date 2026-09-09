from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_mfadevice_last_counter_workspace_notification_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="slack_webhook_url",
            field=models.URLField(
                blank=True,
                help_text="This organisation's Slack incoming webhook. On an installation "
                          "with several organisations, tenant events are posted here or "
                          "nowhere.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="teams_webhook_url",
            field=models.URLField(
                blank=True, help_text="This organisation's Teams incoming webhook.",
                max_length=500,
            ),
        ),
    ]
