from rest_framework.routers import DefaultRouter

from .views import (
    ControlEvidenceViewSet,
    ControlMappingViewSet,
    ControlViewSet,
    FrameworkViewSet,
)

router = DefaultRouter()
router.register("frameworks", FrameworkViewSet)
router.register("controls", ControlViewSet)
router.register("crosswalk", ControlMappingViewSet)
router.register("control-evidence", ControlEvidenceViewSet, basename="controlevidence")

urlpatterns = router.urls
