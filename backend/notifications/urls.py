from django.urls import path

from .views import (
    ChannelsView,
    NotificationDismissView,
    NotificationListView,
    NotificationMarkReadView,
)

urlpatterns = [
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/mark-read/", NotificationMarkReadView.as_view(), name="notifications_mark_read"),
    path("notifications/dismiss/", NotificationDismissView.as_view(), name="notifications_dismiss"),
    # Slack / Teams channels and the emailed digest preference.
    path("notifications/channels/", ChannelsView.as_view(), name="notifications_channels"),
]
