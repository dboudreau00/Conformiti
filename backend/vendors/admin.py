from django.contrib import admin

from .models import Vendor, VendorAssessment


class AssessmentInline(admin.TabularInline):
    model = VendorAssessment
    extra = 0
    fields = ["kind", "title", "issued_at", "expires_at", "result", "document"]


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "tier", "status", "owner", "next_review_date"]
    list_filter = ["tier", "status"]
    search_fields = ["name", "category"]
    inlines = [AssessmentInline]


@admin.register(VendorAssessment)
class VendorAssessmentAdmin(admin.ModelAdmin):
    list_display = ["vendor", "kind", "issued_at", "expires_at", "result"]
    list_filter = ["kind", "result"]
