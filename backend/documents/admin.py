from django.contrib import admin

from .models import Document, DocumentVersion, Folder, FolderPermission, FormTemplate


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


admin.site.register(DocumentVersion)
admin.site.register(FolderPermission)
admin.site.register(FormTemplate)
