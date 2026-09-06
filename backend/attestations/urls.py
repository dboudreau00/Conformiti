from django.urls import path
from rest_framework.routers import DefaultRouter

from .pbc_views import PbcItemViewSet, PbcRequestViewSet
from .views import (
    EvidencePackageViewSet,
    PackageControlViewSet,
    PackageEvidenceViewSet,
    PackageGrantViewSet,
    PackageSampleViewSet,
    SigningKeysView,
)

router = DefaultRouter()
router.register("evidence-packages", EvidencePackageViewSet, basename="evidence-package")
router.register("package-controls", PackageControlViewSet, basename="package-control")
router.register("package-evidence", PackageEvidenceViewSet, basename="package-evidence")
router.register("package-samples", PackageSampleViewSet, basename="package-sample")
router.register("package-grants", PackageGrantViewSet, basename="package-grant")
router.register("pbc-requests", PbcRequestViewSet, basename="pbc-request")
router.register("pbc-items", PbcItemViewSet, basename="pbc-item")

urlpatterns = [
    # The package-signing public keys, for anyone comparing a bundle's key.
    path("signing-keys/", SigningKeysView.as_view(), name="signing_keys"),
] + router.urls
