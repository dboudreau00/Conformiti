from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import AUDITOR_REFUSED, ONLY, is_external_auditor
from documents.access import accessible_folder_ids
from documents.models import Document
from documents.serializers import person_name
from .models import CalendarEvent
from .serializers import CalendarEventSerializer

from rest_framework.permissions import SAFE_METHODS, BasePermission


class ManageCalendarOrReadOnly(BasePermission):
    """Members read, document managers write. An external auditor is refused: the shared calendar names meetings,
    people and dates that are none of their engagement."""

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if is_external_auditor(u):
            self.message = AUDITOR_REFUSED
            return False
        self.message = ONLY["can_manage_documents"]
        return True if request.method in SAFE_METHODS else u.can_manage_documents


FEED_DEFAULT_DAYS = 365   # the window when only one end is given, or neither
FEED_MAX_DAYS = 731       # the widest window one request may ask for


def _feed_window(params):
    """(start, end) of the feed: an unset end falls back to a bounded default, a bad or reversed or too wide one is a
    400. The feed is not paginated, so the window is what bounds it."""
    bounds = {}
    for key in ("start", "end"):
        raw = params.get(key, "")
        if raw:
            try:
                bounds[key] = parse_date(raw)
            except ValueError:
                bounds[key] = None
            if bounds[key] is None:
                raise ValidationError({key: "Use a date as YYYY-MM-DD."})
    today = timezone.localdate()
    try:
        if "start" in bounds and "end" in bounds:
            start, end = bounds["start"], bounds["end"]
        elif "start" in bounds:
            start = bounds["start"]
            end = start + timedelta(days=FEED_DEFAULT_DAYS)
        elif "end" in bounds:
            end = bounds["end"]
            start = end - timedelta(days=FEED_DEFAULT_DAYS)
        else:
            start, end = today - timedelta(days=30), today + timedelta(days=FEED_DEFAULT_DAYS)
    except OverflowError:
        # The default window runs a year past the date given, which the calendar cannot hold near its ends.
        given = "start" if "start" in bounds else "end"
        raise ValidationError({given: "Use a date between 0002-01-01 and 9998-12-31."})
    if end < start:
        raise ValidationError({"end": "The end date is before the start date."})
    if (end - start).days > FEED_MAX_DAYS:
        raise ValidationError({"end": f"Choose a period of at most {FEED_MAX_DAYS} days."})
    return start, end


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
        """Stored events that overlap the window, plus 'review due' events from visible documents that fall in it.
        Without start and end the window is from 30 days ago for a year."""
        start, end = _feed_window(request.query_params)
        items = []
        visible = accessible_folder_ids(request.user)

        # A linked document in a folder the caller cannot open is not named, not even by id.
        for e in self.get_queryset().filter(
                Q(end_date__gte=start) | Q(end_date__isnull=True, date__gte=start), date__lte=end):
            doc = e.document
            items.append({
                "id": f"event-{e.id}", "source": "event", "title": e.title,
                "type": e.event_type, "date": e.date.isoformat(),
                "end_date": e.end_date.isoformat() if e.end_date else None,
                "completed": e.completed,
                "document": doc.id if doc is not None and doc.folder_id in visible else None,
                "assignee": person_name(e.assignee) or None,
            })

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
