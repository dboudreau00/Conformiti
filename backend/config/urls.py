from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts import cookie_auth
from accounts.serializers import MFATokenObtainPairSerializer
from accounts.session_views import AuthConfigView, SessionClearView, SessionView
from accounts.views import LogoutView
from audit.events import record_login_attempt

from .health import HealthView


class LoginRateThrottle(SimpleRateThrottle):
    """Per-IP login limit. ``ScopedRateThrottle`` would read ``throttle_scope`` from views that do not define it,
    which would leave the endpoint unthrottled."""
    scope = "login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login endpoint: per-IP throttle, optional TOTP, every attempt audited. In cookie mode it checks CSRF itself,
    because the usual check only guards a request that already carries a session (login CSRF)."""
    throttle_classes = [LoginRateThrottle]
    serializer_class = MFATokenObtainPairSerializer

    def throttled(self, request, wait):
        """DRF refuses a throttled attempt before ``post`` runs, so record it here, once per client address and minute
        so a flood of refused attempts is not a flood of writes."""
        from django.core.cache import cache

        ident = LoginRateThrottle().get_ident(request)
        if cache.add(f"login-throttled-audit:{ident}", 1, 60):
            record_login_attempt(request, Response(status=429))
        super().throttled(request, wait)

    def post(self, request, *args, **kwargs):
        refused = cookie_auth.csrf_required(request)
        if refused:
            return Response({"detail": f"CSRF failed: {refused}"}, status=403)
        try:
            response = super().post(request, *args, **kwargs)
        except APIException as exc:
            # A rejected password or OTP is an exception, not a response: render it so the failure is still audited.
            response = self.handle_exception(exc)
        record_login_attempt(request, response)
        if cookie_auth.cookie_mode() and response.status_code == 200:
            cookie_auth.set_auth_cookies(
                response, response.data.get("access"), response.data.get("refresh"))
            # Tokens leave only in Set-Cookie: in the body too, they would hand script what HttpOnly hides.
            response.data = {"authenticated": True}
            cookie_auth.rotate_csrf(request)
        return response


class RefreshRateThrottle(SimpleRateThrottle):
    scope = "refresh"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [RefreshRateThrottle]

    def post(self, request, *args, **kwargs):
        refused = cookie_auth.csrf_required(request)
        if refused:
            return Response({"detail": f"CSRF failed: {refused}"}, status=403)
        if cookie_auth.cookie_mode() and not request.data.get("refresh"):
            cookie = request.COOKIES.get(cookie_auth.refresh_cookie_name())
            if cookie:
                # A form body is an immutable QueryDict: work on a copy.
                data = request.data.copy()
                data["refresh"] = cookie
                request._full_data = data
        response = super().post(request, *args, **kwargs)
        if cookie_auth.cookie_mode() and response.status_code == 200:
            cookie_auth.set_auth_cookies(
                response, response.data.get("access"), response.data.get("refresh"))
            response.data = {"renewed": True}
        return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/token/", ThrottledTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", ThrottledTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/session/", SessionView.as_view(), name="session"),
    path("api/auth/session/clear/", SessionClearView.as_view(), name="session_clear"),
    # The refresh cookie's path covers only this URL, so it is the one sign-out that can revoke the token once the
    # access cookie has expired (REVIEWS.md (0.9.5 review), S-7).
    path("api/auth/token/clear/", SessionClearView.as_view(), name="token_clear"),
    path("api/auth/config/", AuthConfigView.as_view(), name="auth_config"),
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
