"""
The three endpoints cookie mode needs that header mode did not.

* ``GET  /api/auth/session/``       — who am I, and can this session renew?
* ``POST /api/auth/session/clear/`` — sign out, from any state.

``LogoutView`` is untouched. It requires authentication, which is right for a
client holding a token it wants revoked, and wrong for the case cookie mode
introduces: the access cookie has expired, the SPA cannot read or clear the
HttpOnly refresh cookie, and a sign-out that 401s would leave a live 7-day
credential in the browser while the interface said "signed out" — so the next
person at that workstation would be signed back in silently. The clear endpoint
therefore takes anyone, is CSRF-protected, and revokes opportunistically.
"""
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from . import cookie_auth


class SessionView(APIView):
    """Tolerant probe. Never 401s, so the SPA can ask "am I signed in?" without
    the console error a 401 would log on every cold load."""
    authentication_classes = [cookie_auth.CookieJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        user = request.user
        authenticated = bool(user and user.is_authenticated)
        # A dead access cookie plus a live refresh cookie is renewable: the SPA
        # should try /auth/token/refresh/ before bouncing to the login screen.
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
        # Seed the readable CSRF cookie so the first write after a cold load
        # has a token to echo.
        if cookie_auth.cookie_mode():
            from django.middleware.csrf import get_token
            get_token(request)
        return response


class SessionClearView(APIView):
    """Sign out from any state: expired access cookie, no cookie at all, or a
    perfectly good session. Always 200, so a client can always finish clearing
    its own state."""
    authentication_classes = [cookie_auth.CookieJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        from audit.events import record_logout

        # 0.9.5f put this on the three endpoints that SET the auth cookies and
        # missed the one that clears them. The check inside cookie
        # authentication only runs once an access cookie has authenticated,
        # and the whole reason this endpoint exists is the case where that
        # cookie is gone and the refresh cookie is not. SameSite=Lax covers
        # most of it; Chrome's two-minute Lax+POST window does not (0.9.5h).
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
                revoked = 0
        # Belt and braces: revoke every outstanding token for a user we can
        # still identify, so an expired access cookie does not leave siblings
        # alive.
        if request.user and request.user.is_authenticated:
            revoked += _blacklist_all(request.user)
            record_logout(request)

        response = Response({"revoked": revoked, "detail": "Session cleared."})
        cookie_auth.clear_auth_cookies(response)
        cookie_auth.rotate_csrf(request)
        return response


def end_all_sessions(user):
    """End every session this account has, both halves of each one.

    For the recovery paths only: a password change, an administrator setting a
    password, an MFA reset. Those say the account may be in the wrong hands,
    and revoking refresh tokens does not end the session already running -- the
    access token in the hijacked tab keeps answering until it expires, an hour
    by default, after the reset that was meant to end it (0.9.5f, M-4).

    Signing out calls ``_blacklist_all`` instead. It revokes every refresh
    token, which is belt and braces for an expired access cookie, but it does
    not reach across to the person's other browser and close it mid-sentence:
    that is a different act, and not the one the review was about.
    """
    from django.utils import timezone

    # Floored to the second: the ``iat`` claim is whole seconds, so a stamp
    # carrying microseconds would refuse a token minted in the same second,
    # which is the token the person signing in again has just been handed.
    user.sessions_valid_from = timezone.now().replace(microsecond=0)
    user.save(update_fields=["sessions_valid_from"])
    return _blacklist_all(user)


def _blacklist_all(user):
    """Revoke every refresh token this account holds, so no session of it can
    renew itself. The access tokens already issued are unaffected; see
    :func:`end_all_sessions` for the paths where that is not enough."""
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
    """What the SPA needs to know before it can sign anyone in.

    Also where the CSRF cookie comes from. In cookie mode the login endpoint
    checks CSRF (0.9.5f), and a visitor arriving at /login with no session has
    no token to send: this is the request the SPA makes before that one, so
    this is where Django is asked to set it.
    """
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
