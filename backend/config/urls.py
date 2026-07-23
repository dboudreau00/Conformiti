"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.serializers import MFATokenObtainPairSerializer


class LoginRateThrottle(SimpleRateThrottle):
    """Per-IP limit on the login / token-refresh endpoints.

    Subclasses SimpleRateThrottle so its ``scope`` binds directly to the
    THROTTLE_LOGIN rate. (ScopedRateThrottle would instead read the scope from
    a view ``throttle_scope`` attribute these views don't define, which would
    silently leave the endpoint unthrottled.)"""
    scope = "login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


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
