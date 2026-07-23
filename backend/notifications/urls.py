from django.urls import path

from .views import (
    NotificationDismissView,
    NotificationListView,
    NotificationMarkReadView,
)

urlpatterns = [
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/mark-read/", NotificationMarkReadView.as_view(), name="notifications_mark_read"),
    path("notifications/dismiss/", NotificationDismissView.as_view(), name="notifications_dismiss"),
]
