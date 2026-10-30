"""Endpoints cookie mode needs. LogoutView requires authentication, but once the access cookie expires the SPA cannot
clear the HttpOnly refresh cookie, so sign-out takes anyone (CSRF-protected) and revokes opportunistically."""
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from . import cookie_auth


class SessionView(APIView):
    """Tolerant probe: an anonymous visitor gets 200, not a 401 that would log a console error on every cold load."""
    authentication_classes = [cookie_auth.CookieJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        user = request.user
        authenticated = bool(user and user.is_authenticated)
        # Dead access cookie plus live refresh cookie: the SPA should refresh before showing the login screen.
        renewable = bool(
            cookie_auth.cookie_mode()
            and not authenticated
            and request.COOKIES.get(cookie_auth.refresh_cookie_name())
        )
        response = Response({
            "transport": cookie_auth.transport(),
            "authenticated": authenticated,
            "renewable": renewable,
            "username": user.get_username() if authenticated else None,
        })
        # Seeds the readable CSRF cookie, so the first write after a cold load has a token to echo.
        if cookie_auth.cookie_mode():
            from django.middleware.csrf import get_token
            get_token(request)
        return response


class SessionClearView(APIView):
    """Sign out from any state (expired, absent or live session); 200 whenever the CSRF check passes."""
    authentication_classes = [cookie_auth.CookieJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        from audit.events import record_logout

        # Needs its own CSRF check: the one in cookie authentication only runs after an access cookie authenticates,
        # and this endpoint exists for when that cookie is gone. SameSite=Lax misses Chrome's 2-minute Lax+POST window.
        refused = cookie_auth.csrf_required(request)
        if refused:
            return Response({"detail": f"CSRF failed: {refused}"}, status=403)

        revoked = 0
        raw = (request.data.get("refresh")
               or request.COOKIES.get(cookie_auth.refresh_cookie_name()))
        if raw:
            try:
                RefreshToken(raw).blacklist()
                revoked = 1
            except TokenError:
                pass
        # Also revoke the user's other outstanding tokens, so siblings do not outlive an expired access cookie.
        if request.user and request.user.is_authenticated:
            revoked += _blacklist_all(request.user)
            record_logout(request)

        response = Response({"revoked": revoked, "detail": "Session cleared."})
        cookie_auth.clear_auth_cookies(response)
        cookie_auth.rotate_csrf(request)
        return response


def end_all_sessions(user):
    """End every session of the account, refresh and access halves: for the recovery paths (password change or reset,
    MFA reset), where a hijacked tab's access token must stop too (M-4). Sign-out uses ``_blacklist_all`` instead."""
    from django.utils import timezone

    # Floored to the second: ``iat`` is whole seconds, so a stamp with microseconds would refuse the token minted in
    # the same second, which is the one the person signing in again has just been handed.
    user.sessions_valid_from = timezone.now().replace(microsecond=0)
    user.save(update_fields=["sessions_valid_from"])
    return _blacklist_all(user)


def _blacklist_all(user):
    """Revoke every refresh token the account holds. Access tokens already issued keep working until they expire."""
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken, OutstandingToken,
        )
    except ImportError:  # pragma: no cover - the app is always installed here
        return 0
    count = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        count += 1 if created else 0
    return count


class AuthConfigView(APIView):
    """What the SPA needs before anyone can sign in. Also where the CSRF cookie comes from: the login endpoint checks
    CSRF in cookie mode, and a visitor with no session has no token until this request sets one."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        from .oidc import config as oidc_config
        from .saml import config as saml_config

        sso = oidc_config()
        saml = saml_config()
        return Response({
            "transport": cookie_auth.transport(),
            "mfa": True,
            "password_min_length": getattr(settings, "PASSWORD_MIN_LENGTH", 12),
            "oidc": {"enabled": sso.enabled, "label": sso.label if sso.enabled else ""},
            "saml": {"enabled": saml.enabled, "label": saml.label if saml.enabled else ""},
        })
