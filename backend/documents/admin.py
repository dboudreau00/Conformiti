from django.contrib import admin

from .models import Document, DocumentVersion, Folder, FolderPermission, FormTemplate

# The admin stores a file exactly as it is sent: none of the checks the API
# runs on an upload (size, extension, macro and OLE2 content, the malware
# scanner) run there. So it takes no file at all, and the scanner's verdict is
# not the admin's to change either: clearing quarantined_at served a file the
# scanner had matched. Files arrive through the API, where the checks are.
FILE_FIELDS = ("file",)
SCAN_FIELDS = ("scan_status", "scan_signature", "scanned_at", "quarantined_at")


class FolderPermissionInline(admin.TabularInline):
    model = FolderPermission
    extra = 0


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "control", "owner", "is_framework_root")
    list_filter = ("is_framework_root",)
    search_fields = ("name",)
    inlines = [FolderPermissionInline]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "folder", "owner", "status", "review_cadence",
                    "next_review_date", "version")
    list_filter = ("status", "review_cadence")
    search_fields = ("name",)
    readonly_fields = FILE_FIELDS + SCAN_FIELDS

    def has_add_permission(self, request):
        return False


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version", "uploaded_by", "created_at")
    readonly_fields = FILE_FIELDS

    def has_add_permission(self, request):
        return False


admin.site.register(FolderPermission)


@admin.register(FormTemplate)
class FormTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "created_at")
    readonly_fields = FILE_FIELDS

    def has_add_permission(self, request):
        return False
