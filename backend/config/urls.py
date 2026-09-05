"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.exceptions import APIException
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts import cookie_auth
from accounts.serializers import MFATokenObtainPairSerializer
from accounts.session_views import AuthConfigView, SessionClearView, SessionView
from accounts.views import LogoutView
from audit.events import record_login_attempt

from .health import HealthView


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
    TOTP second factor for accounts that have MFA enabled. Every attempt —
    success, bad password, bad/missing OTP — is written to the audit trail."""
    throttle_classes = [LoginRateThrottle]
    serializer_class = MFATokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
        except APIException as exc:
            # A rejected password / OTP surfaces as an exception, not a
            # response; render it here so the failure is still audited.
            response = self.handle_exception(exc)
        record_login_attempt(request, response)
        if cookie_auth.cookie_mode() and response.status_code == 200:
            cookie_auth.set_auth_cookies(
                response, response.data.get("access"), response.data.get("refresh"))
            # The tokens leave in Set-Cookie, not in the body: putting them in
            # both would hand script exactly what the cookies exist to hide.
            response.data = {"authenticated": True}
            cookie_auth.rotate_csrf(request)
        return response


class RefreshRateThrottle(SimpleRateThrottle):
    """Refresh gets its own budget: see THROTTLE_REFRESH in settings."""
    scope = "refresh"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [RefreshRateThrottle]

    def post(self, request, *args, **kwargs):
        """In cookie mode the refresh token arrives as a cookie the SPA cannot
        read, so put it where the serializer expects it, and hand the rotated
        pair back as cookies rather than as JSON."""
        if cookie_auth.cookie_mode() and not request.data.get("refresh"):
            cookie = request.COOKIES.get(cookie_auth.refresh_cookie_name())
            if cookie:
                request.data["refresh"] = cookie
        response = super().post(request, *args, **kwargs)
        if cookie_auth.cookie_mode() and response.status_code == 200:
            cookie_auth.set_auth_cookies(
                response, response.data.get("access"), response.data.get("refresh"))
            response.data = {"renewed": True}
        return response


urlpatterns = [
    path("admin/", admin.site.urls),
    # ops
    path("api/health/", HealthView.as_view(), name="health"),
    # auth
    path("api/auth/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", ThrottledTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/session/", SessionView.as_view(), name="session"),
    path("api/auth/session/clear/", SessionClearView.as_view(), name="session_clear"),
    path("api/auth/config/", AuthConfigView.as_view(), name="auth_config"),
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
    path("api/", include("attestations.urls")),
    path("api/", include("vendors.urls")),
]

if settings.DEBUG and not getattr(settings, "USE_S3", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
