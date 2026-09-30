from django.contrib import admin

from .models import (
    AccessReview,
    AccessReviewItem,
    ChampionGroup,
    GroupMember,
    MeetingMinute,
    MeetingSeries,
)


class AccessReviewItemInline(admin.TabularInline):
    model = AccessReviewItem
    extra = 0
    readonly_fields = ["username", "role_name", "folder_grants", "capabilities"]


@admin.register(AccessReview)
class AccessReviewAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "created_by", "created_at", "completed_at"]
    inlines = [AccessReviewItemInline]

    # A completed review is evidence, here as in the API.
    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status == AccessReview.Status.COMPLETED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status == AccessReview.Status.COMPLETED:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(MeetingSeries)
class MeetingSeriesAdmin(admin.ModelAdmin):
    list_display = ["name", "required_per_year", "owner", "active"]


@admin.register(MeetingMinute)
class MeetingMinuteAdmin(admin.ModelAdmin):
    list_display = ["series", "date", "title", "created_by"]
    list_filter = ["series"]
    # The file arrives through the API, where uploads are checked and
    # scanned (documents/admin.py says why the admin takes none).
    readonly_fields = ["file"]


class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 0


@admin.register(ChampionGroup)
class ChampionGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "created_at"]
    inlines = [GroupMemberInline]
