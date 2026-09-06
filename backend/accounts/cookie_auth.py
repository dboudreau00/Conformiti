"""
HttpOnly cookie authentication: the same SimpleJWT tokens, delivered where
JavaScript cannot read them.

The SPA's default is still the Authorization header, because that is what every
0.2.x deployment runs and flipping it silently would sign everyone out. Set
``AUTH_TRANSPORT=cookie`` to move a deployment across; both modes accept a
Bearer header, so an API client keeps working either way.

**What this buys.** With header auth, any XSS can read the access token *and*
the refresh token out of ``localStorage``. With cookie auth it can still make
requests as the user while the page is open — a cookie is attached
automatically — but it cannot exfiltrate a credential that keeps working after
the tab closes. That is a real reduction, and it is the honest size of it.

**What it costs.** A cookie is sent on every same-site request, so cookie mode
needs CSRF protection that header mode did not. Unsafe methods must carry
``X-CSRFToken`` matching the readable ``csrftoken`` cookie — Django's own
double-submit check, reused rather than reinvented.

Deliberately **same-origin only**. The shipped stack serves the SPA and the API
from one nginx, and the CSP is ``connect-src 'self'``. A split-origin
configuration would need ``SameSite=None; Secure``, a cookie domain and CORS
credentials — four more knobs, each a way to get it subtly wrong — for a
topology the product does not otherwise support.
"""
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
    """`__Host-` when the cookie is Secure: bound to this exact host, Path=/,
    no Domain, so nothing on a sibling subdomain can plant or replace it.
    Browsers refuse the prefix over plain http, hence the plain fallback."""
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
        # Pinned, not configurable: see the module docstring.
        "samesite": "Lax",
    }


def set_auth_cookies(response, access=None, refresh=None):
    """Attach the tokens as HttpOnly cookies, each scoped to what needs it."""
    common = _cookie_kwargs()
    if access is not None:
        response.set_cookie(
            access_cookie_name(), access, path=access_cookie_path(),
            max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            **common,
        )
    if refresh is not None:
        # Scoped to the one endpoint that consumes it. /api/auth/ would put the
        # 7-day refresh token on nine endpoints, including the ones that return
        # the TOTP secret and the backup codes and the ones carrying a password.
        response.set_cookie(
            refresh_cookie_name(), refresh,
            path=getattr(settings, "AUTH_COOKIE_REFRESH_PATH", "/api/auth/token/"),
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            **common,
        )
    return response


def clear_auth_cookies(response):
    """Expire both cookies.

    Hand-rolled rather than ``delete_cookie`` because that drops ``httponly``
    and the configured ``secure`` flag, and a browser will not replace a
    Secure+HttpOnly cookie with one that lacks those attributes.
    """
    common = _cookie_kwargs()
    refresh_path = getattr(settings, "AUTH_COOKIE_REFRESH_PATH", "/api/auth/token/")
    response.set_cookie(access_cookie_name(), "", path=access_cookie_path(), max_age=0, **common)
    response.set_cookie(refresh_cookie_name(), "", path=refresh_path, max_age=0, **common)
    # Cookies set by a release before the prefixed names, so a sign-out after
    # an upgrade leaves nothing behind under the old names.
    for legacy, path in (("conformiti_access", "/api/"), ("conformiti_refresh", refresh_path)):
        if legacy not in (access_cookie_name(), refresh_cookie_name()):
            response.set_cookie(legacy, "", path=path, max_age=0, **common)
    return response


def rotate_csrf(request):
    """Issue a fresh CSRF token across the authentication boundary.

    ``django.contrib.auth.login()`` does this for exactly this reason: the
    CSRF cookie lives a year, is readable by script, and in cookie mode it is
    the only thing standing between a live session cookie and a cross-site
    write. Carrying a pre-login token into a post-login session is a fixation
    hazard for no benefit.
    """
    rotate_token(request)


class _Enforcer(CsrfViewMiddleware):
    """Reuse Django's CSRF check rather than writing a second one."""

    def _reject(self, request, reason):
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate from the access cookie when no Bearer header is present.

    A Bearer header always wins, so scripts and integrations are unaffected by
    the transport setting.
    """

    def get_user(self, validated_token):
        """As SimpleJWT's, but loading the workspace and role in the same
        query and refusing a person whose workspace has been archived."""
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
        """Only a cookie-authenticated unsafe request needs this: a Bearer
        header is not attached by the browser on its own, so it cannot be
        forged cross-site."""
        if request.method in SAFE_METHODS:
            return
        reason = _Enforcer(lambda r: None).process_view(request, None, (), {})
        if reason:
            raise PermissionDenied(f"CSRF failed: {reason}")
