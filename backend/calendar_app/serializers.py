from rest_framework import serializers

from .models import CalendarEvent


class CalendarEventSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(source="assignee.get_full_name", read_only=True, default="")

    class Meta:
        model = CalendarEvent
        fields = [
            "id", "title", "event_type", "date", "end_date", "all_day",
            "description", "document", "control", "framework", "assignee",
            "assignee_name", "completed", "created_by", "created_at",
        ]
        read_only_fields = ["created_by"]
