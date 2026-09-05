from rest_framework.routers import DefaultRouter

from .pbc_views import PbcItemViewSet, PbcRequestViewSet
from .views import (
    EvidencePackageViewSet,
    PackageControlViewSet,
    PackageEvidenceViewSet,
    PackageGrantViewSet,
    PackageSampleViewSet,
)

router = DefaultRouter()
router.register("evidence-packages", EvidencePackageViewSet, basename="evidence-package")
router.register("package-controls", PackageControlViewSet, basename="package-control")
router.register("package-evidence", PackageEvidenceViewSet, basename="package-evidence")
router.register("package-samples", PackageSampleViewSet, basename="package-sample")
router.register("package-grants", PackageGrantViewSet, basename="package-grant")
router.register("pbc-requests", PbcRequestViewSet, basename="pbc-request")
router.register("pbc-items", PbcItemViewSet, basename="pbc-item")

urlpatterns = router.urls
