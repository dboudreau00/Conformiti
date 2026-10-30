"""The SimpleJWT tokens as HttpOnly cookies (AUTH_TRANSPORT=cookie); a Bearer header works in both modes.
Cookie mode needs CSRF: unsafe methods must carry X-CSRFToken (Django's double-submit check). Same-origin only."""
from datetime import datetime, timezone

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware, rotate_token
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")


def transport():
    return getattr(settings, "AUTH_TRANSPORT", "header")


def cookie_mode():
    return transport() == "cookie"


def _secure():
    return bool(getattr(settings, "AUTH_COOKIE_SECURE", not settings.DEBUG))


def access_cookie_name():
    """`__Host-` when the cookie is Secure: bound to this host with Path=/ and no Domain, so a sibling subdomain cannot
    plant or replace it. Browsers refuse the prefix over plain http, hence the plain fallback."""
    configured = getattr(settings, "AUTH_COOKIE_ACCESS", "") or ""
    if configured:
        return configured
    return "__Host-conformiti_access" if _secure() else "conformiti_access"


def refresh_cookie_name():
    """`__Secure-` rather than `__Host-`: the host prefix would force Path=/,
    and the refresh token's narrow path is worth more than the prefix."""
    configured = getattr(settings, "AUTH_COOKIE_REFRESH", "") or ""
    if configured:
        return configured
    return "__Secure-conformiti_refresh" if _secure() else "conformiti_refresh"


def access_cookie_path():
    return "/" if access_cookie_name().startswith("__Host-") else "/api/"


def _cookie_kwargs():
    return {
        "httponly": True,
        "secure": _secure(),
        "samesite": "Lax",
    }


def set_auth_cookies(response, access=None, refresh=None):
    common = _cookie_kwargs()
    if access is not None:
        response.set_cookie(
            access_cookie_name(), access, path=access_cookie_path(),
            max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            **common,
        )
    if refresh is not None:
        # Scoped to the one endpoint that consumes it: /api/auth/ would send the 7-day refresh token to the endpoints
        # that return the TOTP secret and backup codes or carry a password.
        response.set_cookie(
            refresh_cookie_name(), refresh,
            path=getattr(settings, "AUTH_COOKIE_REFRESH_PATH", "/api/auth/token/"),
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            **common,
        )
    return response


def clear_auth_cookies(response):
    """Expire both cookies. Not ``delete_cookie``: it drops ``httponly`` and ``secure``, and a browser will not replace
    a Secure+HttpOnly cookie with one that lacks them."""
    common = _cookie_kwargs()
    refresh_path = getattr(settings, "AUTH_COOKIE_REFRESH_PATH", "/api/auth/token/")
    response.set_cookie(access_cookie_name(), "", path=access_cookie_path(), max_age=0, **common)
    response.set_cookie(refresh_cookie_name(), "", path=refresh_path, max_age=0, **common)
    # Also expire the unprefixed names, so a sign-out after an upgrade leaves nothing behind.
    for legacy, path in (("conformiti_access", "/api/"), ("conformiti_refresh", refresh_path)):
        if legacy not in (access_cookie_name(), refresh_cookie_name()):
            response.set_cookie(legacy, "", path=path, max_age=0, **common)
    return response


def rotate_csrf(request):
    """Issue a fresh CSRF token across the authentication boundary, as ``django.contrib.auth.login()`` does: a token
    carried over is a fixation hazard, and in cookie mode the CSRF cookie guards the session cookie."""
    rotate_token(request)


class _Enforcer(CsrfViewMiddleware):
    """Django's CSRF check, answering with the failure reason instead of a response."""

    def _reject(self, request, reason):
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticates from the access cookie when no Bearer header is present; a Bearer header always wins."""

    def get_user(self, validated_token):
        """SimpleJWT's, plus workspace and role loaded in the same query and a refusal for an archived workspace."""
        from rest_framework_simplejwt.exceptions import InvalidToken
        from rest_framework_simplejwt.settings import api_settings

        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError as exc:
            raise InvalidToken("Token contained no recognizable user identification") from exc
        try:
            user = (self.user_model.objects.select_related("workspace", "role")
                    .get(**{api_settings.USER_ID_FIELD: user_id}))
        except self.user_model.DoesNotExist as exc:
            raise AuthenticationFailed("User not found", code="user_not_found") from exc
        if api_settings.CHECK_USER_IS_ACTIVE and not user.is_active:
            raise AuthenticationFailed("User is inactive", code="user_inactive")
        if user.workspace_id and not user.workspace.is_active and not user.is_superuser:
            raise AuthenticationFailed("This workspace is archived.", code="workspace_archived")
        _refuse_if_superseded(user, validated_token)
        return user

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            return super().authenticate(request)
        if not cookie_mode():
            return None
        raw = request.COOKIES.get(access_cookie_name())
        if not raw:
            return None
        validated = self.get_validated_token(raw)
        self._enforce_csrf(request)
        return self.get_user(validated), validated

    def _enforce_csrf(self, request):
        """Cookie-authenticated unsafe requests only: a browser does not attach a Bearer header on its own."""
        if request.method in SAFE_METHODS:
            return
        reason = _Enforcer(lambda r: None).process_view(request, None, (), {})
        if reason:
            raise PermissionDenied(f"CSRF failed: {reason}")


def _refuse_if_superseded(user, validated_token):
    """Refuse an access token minted before the account's sessions were ended: blacklisting reaches refresh tokens only.
    A token with no ``iat`` is refused rather than trusted."""
    stamped = getattr(user, "sessions_valid_from", None)
    if not stamped:
        return
    issued = validated_token.payload.get("iat")
    if issued is None or datetime.fromtimestamp(int(issued), tz=timezone.utc) < stamped:
        raise AuthenticationFailed(
            "This session was ended. Sign in again.", code="session_superseded")


def csrf_required(request):
    """Django's CSRF check for a view that authenticates nobody (the cookie-setting endpoints), so login cannot be
    forged cross-site. Returns a reason string on failure; None on pass, and in header mode."""
    if not cookie_mode():
        return None
    return _Enforcer(lambda r: None).process_view(request, None, (), {})
