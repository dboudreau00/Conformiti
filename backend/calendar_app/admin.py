from django.contrib import admin

from .models import CalendarEvent


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("date", "title", "event_type", "assignee", "completed")
    list_filter = ("event_type", "completed")
    search_fields = ("title",)
