from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    MfaBackupCodesView,
    MfaDisableView,
    MfaSetupView,
    MfaStatusView,
    MfaVerifyView,
    RoleViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register("roles", RoleViewSet)
router.register("users", UserViewSet)

urlpatterns = [
    path("auth/mfa/status/", MfaStatusView.as_view(), name="mfa_status"),
    path("auth/mfa/setup/", MfaSetupView.as_view(), name="mfa_setup"),
    path("auth/mfa/verify/", MfaVerifyView.as_view(), name="mfa_verify"),
    path("auth/mfa/disable/", MfaDisableView.as_view(), name="mfa_disable"),
    path("auth/mfa/backup-codes/", MfaBackupCodesView.as_view(), name="mfa_backup_codes"),
] + router.urls
