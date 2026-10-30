from django.urls import path
from rest_framework.routers import DefaultRouter

from .public_views import QuestionnaireSubmitView, QuestionnaireView
from .views import QuestionnaireInviteViewSet, VendorAssessmentViewSet, VendorViewSet

router = DefaultRouter()
router.register("vendors", VendorViewSet)
router.register("vendor-assessments", VendorAssessmentViewSet)
router.register("questionnaire-invites", QuestionnaireInviteViewSet, basename="questionnaire-invite")

urlpatterns = [
    # Unauthenticated, keyed by the token in the emailed link (vendors/questionnaire.py).
    path("questionnaire/<str:token>/", QuestionnaireView.as_view(), name="questionnaire_public"),
    path("questionnaire/<str:token>/submit/", QuestionnaireSubmitView.as_view(),
         name="questionnaire_submit"),
] + router.urls
