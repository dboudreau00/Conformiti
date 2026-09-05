"""The three HTTP faces of the OIDC flow: start, callback, redeem."""
from urllib.parse import quote

from django.contrib.auth.models import update_last_login
from django.http import HttpResponseRedirect
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from . import cookie_auth, oidc


class _LoginThrottle(SimpleRateThrottle):
    """Same per-IP budget as the password login (THROTTLE_LOGIN)."""
    scope = "login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def _fail(request, exc):
    oidc.audit(request, None, False, f"sso sign-in failed ({exc.code}): {exc.detail or exc.message}")
    return HttpResponseRedirect("/login?sso_error=" + quote(exc.code, safe=""))


class OidcStartView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [_LoginThrottle]

    def get(self, request):
        try:
            url = oidc.begin(request, request.GET.get("next", "/"))
        except oidc.OidcError as exc:
            return _fail(request, exc)
        return HttpResponseRedirect(url)


class OidcCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [_LoginThrottle]

    def get(self, request):
        try:
            user, how, next_path, asserted = oidc.complete(request)
            step_up = oidc.step_up_needed(user, asserted)
        except oidc.OidcError as exc:
            return _fail(request, exc)
        ticket = oidc.issue_ticket(request, user, mfa_pending=step_up)
        oidc.audit(request, user, True,
                   f"sso sign-in ({how}{'; step-up pending' if step_up else ''}): "
                   f"{user.get_username()} via {oidc.config().issuer}")
        return HttpResponseRedirect(f"/login?sso={quote(ticket, safe='')}&next={quote(next_path, safe='/')}")


class OidcRedeemView(APIView):
    """Turn a one-time ticket into tokens, exactly as a password login would
    hand them out: JSON in header mode, HttpOnly cookies in cookie mode."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [_LoginThrottle]

    def post(self, request):
        from . import passkeys

        otp = request.data.get("otp")
        passkey = request.data.get("passkey")
        try:
            user = oidc.redeem_ticket(request, request.data.get("ticket"), otp, passkey)
        except oidc.StepUpRequired as pending:
            payload = {"mfa_required": True, "factors": passkeys.factors(pending.user)}
            if payload["factors"]["passkey"]:
                payload["passkey"] = passkeys.begin_login(pending.user, request)
            return Response(payload)
        except oidc.OidcError as exc:
            oidc.audit(request, None, False, f"sso ticket refused ({exc.code}): {exc.detail}")
            return Response({"detail": exc.message, "code": exc.code}, status=400)
        if otp is not None or passkey is not None:
            how = "passkey verified" if passkey is not None else "second factor verified"
            oidc.audit(request, user, True, f"sso step-up: {how} for {user.get_username()}")
        refresh = RefreshToken.for_user(user)
        access = str(refresh.access_token)
        update_last_login(None, user)
        response = Response({"access": access, "refresh": str(refresh)})
        if cookie_auth.cookie_mode():
            cookie_auth.set_auth_cookies(response, access, str(refresh))
            response.data = {"authenticated": True}
            cookie_auth.rotate_csrf(request)
        return response
