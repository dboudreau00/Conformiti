from rest_framework.routers import DefaultRouter

from .views import (
    EvidencePackageViewSet,
    PackageControlViewSet,
    PackageEvidenceViewSet,
    PackageGrantViewSet,
)

router = DefaultRouter()
router.register("evidence-packages", EvidencePackageViewSet, basename="evidence-package")
router.register("package-controls", PackageControlViewSet, basename="package-control")
router.register("package-evidence", PackageEvidenceViewSet, basename="package-evidence")
router.register("package-grants", PackageGrantViewSet, basename="package-grant")

urlpatterns = router.urls
