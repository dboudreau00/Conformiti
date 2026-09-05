from django.urls import path
from rest_framework.routers import DefaultRouter

from .oidc_views import OidcCallbackView, OidcRedeemView, OidcStartView
from .saml_views import SamlAcsView, SamlMetadataView, SamlStartView
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
    # Single sign-on (OpenID Connect). Configured from the environment only.
    path("auth/oidc/start/", OidcStartView.as_view(), name="oidc_start"),
    path("auth/oidc/callback/", OidcCallbackView.as_view(), name="oidc_callback"),
    path("auth/oidc/redeem/", OidcRedeemView.as_view(), name="oidc_redeem"),
    # Single sign-on (SAML 2.0). Same ticket redemption as OIDC.
    path("auth/saml/start/", SamlStartView.as_view(), name="saml_start"),
    path("auth/saml/acs/", SamlAcsView.as_view(), name="saml_acs"),
    path("auth/saml/metadata/", SamlMetadataView.as_view(), name="saml_metadata"),
] + router.urls
