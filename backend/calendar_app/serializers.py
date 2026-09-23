from rest_framework import serializers

from documents.access import accessible_folder_ids
from documents.serializers import PersonNameField

from .models import CalendarEvent


class CalendarEventSerializer(serializers.ModelSerializer):
    assignee_name = PersonNameField("assignee")

    class Meta:
        model = CalendarEvent
        fields = [
            "id", "title", "event_type", "date", "end_date", "all_day",
            "description", "document", "control", "framework", "assignee",
            "assignee_name", "completed", "created_by", "created_at",
        ]
        read_only_fields = ["created_by"]

    def to_representation(self, instance):
        """Withhold a linked document the reader cannot open.

        The merged feed already does this; the list and detail routes must not
        hand back the id it hides. Writes still accept the id.
        """
        data = super().to_representation(instance)
        if instance.document_id is not None:
            visible = self._visible_folders()
            if visible is not None and instance.document.folder_id not in visible:
                data["document"] = None
        return data

    def _visible_folders(self):
        """The reader's folders, worked out once per request.

        A list serializer shares its context with every row, so the folder walk
        runs once for the page rather than once per event.
        """
        request = self.context.get("request")
        if request is None:
            return None
        if "_visible_folder_ids" not in self.context:
            self.context["_visible_folder_ids"] = accessible_folder_ids(request.user)
        return self.context["_visible_folder_ids"]
