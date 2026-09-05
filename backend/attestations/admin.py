from django.contrib import admin

from .models import EvidencePackage, PackageControl, PackageEvidence, PackageGrant, PbcRequest


@admin.register(PbcRequest)
class PbcRequestAdmin(admin.ModelAdmin):
    list_display = ["reference", "title", "package", "status", "due_date", "assignee_name"]
    list_filter = ["status", "priority"]


@admin.register(EvidencePackage)
class EvidencePackageAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "assurance_type", "sealed_at", "manifest_sha256"]
    list_filter = ["status", "assurance_type"]
    readonly_fields = ["manifest_sha256", "manifest_json", "sealed_at", "asserted_at"]


@admin.register(PackageControl)
class PackageControlAdmin(admin.ModelAdmin):
    list_display = ["control_ref", "title", "package", "design_conclusion", "operating_conclusion"]
    list_filter = ["design_conclusion", "operating_conclusion"]


@admin.register(PackageEvidence)
class PackageEvidenceAdmin(admin.ModelAdmin):
    list_display = ["document_name", "pinned_version", "size_bytes", "content_sha256"]


@admin.register(PackageGrant)
class PackageGrantAdmin(admin.ModelAdmin):
    list_display = ["username", "package", "granted_at", "expires_at", "revoked_at", "access_count"]
