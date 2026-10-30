from django.contrib import admin

from .models import JiraBoard, JiraIntegration


@admin.register(JiraIntegration)
class JiraIntegrationAdmin(admin.ModelAdmin):
    list_display = ["base_url", "email", "enabled", "updated_at"]
    # The field decrypts on access, so a default form would show the token in plain text: set it through the API.
    exclude = ["api_token"]


@admin.register(JiraBoard)
class JiraBoardAdmin(admin.ModelAdmin):
    list_display = ["name", "board_id", "created_at"]
