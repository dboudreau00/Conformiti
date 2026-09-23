"""Calendar API: CRUD for events plus a merged feed for the dashboard."""
from datetime import date

from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import is_external_auditor
from documents.access import accessible_folder_ids
from documents.models import Document
from documents.serializers import person_name
from .models import CalendarEvent
from .serializers import CalendarEventSerializer

from rest_framework.permissions import SAFE_METHODS, BasePermission


class ManageCalendarOrReadOnly(BasePermission):
    """Any member of the organisation can read the calendar; only users who
    manage documents may create, edit, or delete events (prevents read-only
    Viewers from tampering with everyone's shared calendar).

    An external auditor is not a member: the shared calendar names meetings,
    people and dates that are none of their engagement.
    """

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated) or is_external_auditor(u):
            return False
        return True if request.method in SAFE_METHODS else u.can_manage_documents


class CalendarEventViewSet(viewsets.ModelViewSet):
    queryset = CalendarEvent.objects.select_related(
        "document", "control", "framework", "assignee"
    ).all()
    serializer_class = CalendarEventSerializer
    permission_classes = [ManageCalendarOrReadOnly]
    filterset_fields = ["event_type", "completed", "assignee", "framework"]
    search_fields = ["title", "description"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"])
    def feed(self, request):
        """
        Merge stored events with virtual 'review due' events derived from each
        visible document's next_review_date, within an optional [start, end].
        """
        start = parse_date(request.query_params.get("start", "")) or date.min
        end = parse_date(request.query_params.get("end", "")) or date.max
        items = []
        visible = accessible_folder_ids(request.user)

        # stored events; a linked document in a folder the caller cannot open
        # is not named, not even by id
        for e in self.get_queryset().filter(date__gte=start, date__lte=end):
            doc = e.document
            items.append({
                "id": f"event-{e.id}", "source": "event", "title": e.title,
                "type": e.event_type, "date": e.date.isoformat(),
                "end_date": e.end_date.isoformat() if e.end_date else None,
                "completed": e.completed,
                "document": doc.id if doc is not None and doc.folder_id in visible else None,
                "assignee": person_name(e.assignee) or None,
            })

        # virtual review-due events from visible documents
        docs = Document.objects.filter(
            folder_id__in=visible, next_review_date__isnull=False,
            next_review_date__gte=start, next_review_date__lte=end,
        ).select_related("owner", "folder")
        for d in docs:
            items.append({
                "id": f"review-{d.id}", "source": "review",
                "title": f"Review due: {d.name}", "type": "review_due",
                "date": d.next_review_date.isoformat(), "end_date": None,
                "completed": False, "document": d.id,
                "assignee": person_name(d.owner) or None,
                "overdue": d.is_overdue,
            })

        items.sort(key=lambda x: x["date"])
        return Response(items)
