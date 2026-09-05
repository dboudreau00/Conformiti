from rest_framework.routers import DefaultRouter

from .views import VendorAssessmentViewSet, VendorViewSet

router = DefaultRouter()
router.register("vendors", VendorViewSet)
router.register("vendor-assessments", VendorAssessmentViewSet)

urlpatterns = router.urls
