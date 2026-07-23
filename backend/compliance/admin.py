from django.contrib import admin

from .models import Control, ControlCategory, ControlMapping, Framework


class ControlInline(admin.TabularInline):
    model = Control
    extra = 0
    fields = ("control_id", "title", "status", "owner")


@admin.register(Framework)
class FrameworkAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "authority")


@admin.register(ControlCategory)
class ControlCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "framework", "order")
    list_filter = ("framework",)
    inlines = [ControlInline]


@admin.register(Control)
class ControlAdmin(admin.ModelAdmin):
    list_display = ("control_id", "title", "category", "status", "owner")
    list_filter = ("status", "category__framework")
    search_fields = ("control_id", "title")


admin.site.register(ControlMapping)
