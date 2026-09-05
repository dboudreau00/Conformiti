from rest_framework.routers import DefaultRouter

from .responsibility_views import ResponsibilityViewSet
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
router.register("responsibilities", ResponsibilityViewSet)

urlpatterns = router.urls
