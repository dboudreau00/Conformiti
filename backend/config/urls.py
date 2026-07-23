"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.serializers import MFATokenObtainPairSerializer


class LoginRateThrottle(ScopedRateThrottle):
    scope = "login"


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login endpoint: tight per-IP rate limit (THROTTLE_LOGIN) + optional
    TOTP second factor for accounts that have MFA enabled."""
    throttle_classes = [LoginRateThrottle]
    serializer_class = MFATokenObtainPairSerializer


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [LoginRateThrottle]


urlpatterns = [
    path("admin/", admin.site.urls),
    # auth
    path("api/auth/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", ThrottledTokenRefreshView.as_view(), name="token_refresh"),
    # apps
    path("api/", include("accounts.urls")),
    path("api/", include("audit.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("compliance.urls")),
    path("api/", include("documents.urls")),
    path("api/", include("calendar_app.urls")),
    path("api/", include("analytics.urls")),
    path("api/", include("governance.urls")),
    path("api/", include("integrations.urls")),
]

if settings.DEBUG and not getattr(settings, "USE_S3", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
