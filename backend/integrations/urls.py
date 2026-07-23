from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import JiraBoardViewSet, JiraConfigView, JiraTestView

router = DefaultRouter()
router.register("integrations/jira/boards", JiraBoardViewSet)

urlpatterns = [
    path("integrations/jira/config/", JiraConfigView.as_view(), name="jira-config"),
    path("integrations/jira/test/", JiraTestView.as_view(), name="jira-test"),
] + router.urls
