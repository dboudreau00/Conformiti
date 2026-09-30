from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "object_type", "object_id", "ip_address")
    list_filter = ("action", "object_type")
    search_fields = ("detail", "object_id")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    # The trail is read-only here as it is in the API: nobody, a superuser
    # included, adds, edits or deletes an entry. Deleting was left at Django's
    # default until 0.9.5mb, so "Delete selected" could clear the trail.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
