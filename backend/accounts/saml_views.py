"""The HTTP faces of SAML: start, the assertion consumer, and SP metadata."""
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from . import oidc, saml
from .oidc_views import _LoginThrottle, _fail


def _flow_cookie(response, request, value):
    """Set (or clear) the flow cookie. The provider posts back cross-site, so
    the cookie has to be SameSite=None -- which browsers accept only with
    Secure. Over plain http (a developer's box) it falls back to Lax."""
    secure = request.is_secure() or bool(getattr(settings, "BEHIND_TLS", False))
    if value is None:
        response.set_cookie(saml.FLOW_COOKIE, "", max_age=0, path="/api/auth/saml/",
                            httponly=True, secure=secure, samesite="None" if secure else "Lax")
    else:
        response.set_cookie(saml.FLOW_COOKIE, value, max_age=saml.FLOW_TTL, path="/api/auth/saml/",
                            httponly=True, secure=secure, samesite="None" if secure else "Lax")
    return response


class SamlStartView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [_LoginThrottle]

    def get(self, request):
        try:
            url, cookie = saml.begin(request, request.GET.get("next", "/"))
        except oidc.OidcError as exc:
            return _fail(request, exc)
        return _flow_cookie(HttpResponseRedirect(url), request, cookie)


class SamlAcsView(APIView):
    """Where the provider posts the signed Response. Never authenticated: the
    browser arriving here carries nothing but the flow cookie."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [_LoginThrottle]

    def post(self, request):
        flow = saml.read_flow(request)
        try:
            user, how, next_path, mfa_asserted = saml.complete(request, flow)
            step_up = oidc.step_up_needed(user, mfa_asserted)
        except oidc.OidcError as exc:
            return _flow_cookie(_fail(request, exc), request, None)
        ticket = oidc.issue_ticket(request, user, mfa_pending=step_up)
        oidc.audit(request, user, True,
                   f"sso sign-in ({how}; saml{'; step-up pending' if step_up else ''}): "
                   f"{user.get_username()} via {saml.config().idp_entity_id}")
        response = HttpResponseRedirect(
            f"/login?sso={quote(ticket, safe='')}&next={quote(next_path, safe='/')}")
        return _flow_cookie(response, request, None)


class SamlMetadataView(APIView):
    """Our SP metadata, for the provider's administrator to import."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        if not saml.config().enabled:
            return HttpResponse("SAML is not configured on this server.\n",
                                content_type="text/plain", status=404)
        return HttpResponse(saml.metadata_xml(request), content_type="application/samlmetadata+xml")
