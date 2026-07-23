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


@admin.register(MeetingSeries)
class MeetingSeriesAdmin(admin.ModelAdmin):
    list_display = ["name", "required_per_year", "owner", "active"]


@admin.register(MeetingMinute)
class MeetingMinuteAdmin(admin.ModelAdmin):
    list_display = ["series", "date", "title", "created_by"]
    list_filter = ["series"]


class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 0


@admin.register(ChampionGroup)
class ChampionGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "created_at"]
    inlines = [GroupMemberInline]
