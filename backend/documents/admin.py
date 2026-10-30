from django.contrib import admin

from .models import Document, DocumentVersion, Folder, FolderPermission, FormTemplate

# The admin runs none of the API's upload checks (size, type, macros, scanner), so it takes no file; the scanner's
# verdict is read-only there too: clearing quarantined_at would serve a file the scanner matched.
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
