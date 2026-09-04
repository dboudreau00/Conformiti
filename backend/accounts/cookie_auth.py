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
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")


def transport():
    return getattr(settings, "AUTH_TRANSPORT", "header")


def cookie_mode():
    return transport() == "cookie"


def access_cookie_name():
    return getattr(settings, "AUTH_COOKIE_ACCESS", "conformiti_access")


def refresh_cookie_name():
    return getattr(settings, "AUTH_COOKIE_REFRESH", "conformiti_refresh")


def _cookie_kwargs():
    return {
        "httponly": True,
        "secure": bool(getattr(settings, "AUTH_COOKIE_SECURE", not settings.DEBUG)),
        # Pinned, not configurable: see the module docstring.
        "samesite": "Lax",
    }


def set_auth_cookies(response, access=None, refresh=None):
    """Attach the tokens as HttpOnly cookies, each scoped to what needs it."""
    common = _cookie_kwargs()
    if access is not None:
        response.set_cookie(
            access_cookie_name(), access, path="/api/",
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
    response.set_cookie(access_cookie_name(), "", path="/api/", max_age=0, **common)
    response.set_cookie(
        refresh_cookie_name(), "",
        path=getattr(settings, "AUTH_COOKIE_REFRESH_PATH", "/api/auth/token/"),
        max_age=0, **common,
    )
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
