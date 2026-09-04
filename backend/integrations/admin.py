from django.contrib import admin

from .models import JiraBoard, JiraIntegration


@admin.register(JiraIntegration)
class JiraIntegrationAdmin(admin.ModelAdmin):
    list_display = ["base_url", "email", "enabled", "updated_at"]
    # The model field decrypts on attribute access, so a default change form
    # would render the token in a plain text input -- undoing the encryption in
    # the one UI it is most likely to be read from. Set it through the API.
    exclude = ["api_token"]


@admin.register(JiraBoard)
class JiraBoardAdmin(admin.ModelAdmin):
    list_display = ["name", "board_id", "created_at"]
