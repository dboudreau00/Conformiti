from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Role, User, WebAuthnCredential, Workspace

admin.site.register(Role)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")


@admin.register(WebAuthnCredential)
class WebAuthnCredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "algorithm", "sign_count", "created_at", "last_used_at", "suspect_at")
    readonly_fields = ("credential_id", "public_key", "algorithm", "sign_count", "aaguid",
                       "transports", "created_at", "last_used_at", "suspect_at", "suspect_reason")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Compliance", {"fields": ("role", "job_title")}),)
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
