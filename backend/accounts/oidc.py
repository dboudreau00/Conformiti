"""
Single sign-on over OpenID Connect (authorization code + PKCE).

The provider is configured from the environment only -- never from a database
row an administrator could create. A settable "trusted issuer" would let
anyone with the users capability point the app at an identity provider they
control and mint themselves any account; keeping it in the environment keeps
it with the person who deploys the software.

What the flow does, in order:

1. ``begin``     -- discover the provider, generate ``state``, ``nonce`` and a
                    PKCE verifier, park them in the Django session, redirect.
2. ``complete``  -- check ``state``, exchange the code (no redirects, https,
                    bounded body), verify the ID token's signature against the
                    provider's JWKS, its issuer, audience, expiry and ``nonce``,
                    then map the identity to a local user.
3. ``redeem``    -- the SPA turns a one-time ticket into the same tokens a
                    password login produces, in whichever transport is live.

Mapping rules, in order of trust:

* an identity already linked (issuer + subject) signs in as that user;
* otherwise a verified email that matches exactly one local account links
  it -- unless that account is a superuser or staff, which must always use
  their password (an IdP admin must not be able to become the app admin);
* otherwise, if ``OIDC_AUTO_PROVISION`` is on and the domain is allowed, a
  new account is created with ``OIDC_DEFAULT_ROLE`` -- which is refused if
  that role can manage users;
* otherwise the sign-in is declined, and the reason is in the audit trail.

Local MFA is not asked for on an SSO login: the provider authenticated the
person, and that is where step-up policy belongs. Password logins are
unaffected.
"""
import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from audit.middleware import _client_ip
from audit.models import AuditLog

from .models import OidcIdentity, Role

log = logging.getLogger(__name__)

SESSION_KEY = "oidc_flow"
FLOW_TTL = 600          # seconds a started sign-in stays valid
TICKET_TTL = 90         # seconds the SPA has to redeem a finished sign-in
DISCOVERY_TTL = 3600
MAX_BODY = 1 << 20
ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "ES256", "ES384"]

# Reasons the login screen can show. Anything not listed reads as "denied".
MESSAGES = {
    "disabled": "Single sign-on is not configured on this server.",
    "state": "That sign-in link expired or was already used. Start again.",
    "provider": "The identity provider could not be reached. Try again in a moment.",
    "token": "The identity provider's response could not be verified.",
    "denied": "The identity provider declined the sign-in.",
    "no_email": "The identity provider did not share an email address.",
    "unverified_email": "The identity provider has not verified that email address.",
    "domain": "That email domain is not allowed to sign in here.",
    "privileged": "Administrator accounts sign in with their password.",
    "ambiguous_email": "More than one account uses that email address. Ask an administrator to link your identity.",
    "unknown_user": "No account is linked to that identity. Ask an administrator to link it.",
    "inactive": "That account is deactivated.",
    "role": "The server's default single sign-on role is misconfigured.",
    "mfa_required": "This server requires a second factor for single sign-on. Sign in with your "
                    "password once and enrol an authenticator, or have your identity provider assert one.",
    "mfa_invalid": "That authentication code isn't valid.",
}


class StepUpRequired(Exception):
    """The ticket is good, but the local second factor has not been given yet.
    Carries the user so the view can say which factors are on offer."""

    def __init__(self, user=None):
        super().__init__("step-up required")
        self.user = user


class OidcError(Exception):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(detail or code)

    @property
    def message(self):
        return MESSAGES.get(self.code, MESSAGES["denied"])


@dataclass(frozen=True)
class Config:
    issuer: str
    client_id: str
    client_secret: str
    scopes: str
    label: str
    redirect_uri: str
    allowed_domains: tuple
    auto_provision: bool
    default_role: str
    link_by_email: bool
    require_verified_email: bool

    @property
    def enabled(self):
        return bool(self.issuer and self.client_id and self.client_secret)


def config():
    """Read at call time so tests and reloads see the live settings."""
    domains = getattr(settings, "OIDC_ALLOWED_DOMAINS", []) or []
    return Config(
        issuer=str(getattr(settings, "OIDC_ISSUER", "") or "").strip().rstrip("/"),
        client_id=str(getattr(settings, "OIDC_CLIENT_ID", "") or "").strip(),
        client_secret=str(getattr(settings, "OIDC_CLIENT_SECRET", "") or ""),
        scopes=str(getattr(settings, "OIDC_SCOPES", "openid email profile") or "openid email profile"),
        label=str(getattr(settings, "OIDC_LABEL", "Single sign-on") or "Single sign-on"),
        redirect_uri=str(getattr(settings, "OIDC_REDIRECT_URI", "") or "").strip(),
        allowed_domains=tuple(d.strip().lower().lstrip("@") for d in domains if d and d.strip()),
        auto_provision=bool(getattr(settings, "OIDC_AUTO_PROVISION", False)),
        default_role=str(getattr(settings, "OIDC_DEFAULT_ROLE", "Viewer") or "Viewer"),
        link_by_email=bool(getattr(settings, "OIDC_LINK_BY_EMAIL", True)),
        require_verified_email=bool(getattr(settings, "OIDC_REQUIRE_VERIFIED_EMAIL", True)),
    )


# --------------------------------------------------------------------------- #
# Talking to the provider
# --------------------------------------------------------------------------- #
class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A provider endpoint that redirects is either misconfigured or hostile;
    following it would let discovery walk the request somewhere else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OidcError("provider", "the identity provider redirected an API call")


_opener = urllib.request.build_opener(_NoRedirects)


def _http(url, data=None, headers=None):
    """GET (or POST form ``data``) a JSON document over https, no redirects,
    body capped. Patched wholesale in tests."""
    if not str(url).startswith("https://") and not settings.DEBUG:
        raise OidcError("provider", "identity provider URLs must be https")
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **(headers or {})})
    try:
        with _opener.open(req, timeout=8) as resp:
            body = resp.read(MAX_BODY + 1)
    except OidcError:
        raise
    except urllib.error.HTTPError as exc:
        raise OidcError("provider", f"{url.split('?', 1)[0]} answered {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OidcError("provider", f"could not reach the identity provider: {exc}")
    if len(body) > MAX_BODY:
        raise OidcError("provider", "identity provider response too large")
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise OidcError("provider", "identity provider returned something that is not JSON")


def _cache_key(kind, cfg):
    return f"oidc:{kind}:" + hashlib.sha256(cfg.issuer.encode("utf-8")).hexdigest()[:24]


def discovery(cfg):
    doc = cache.get(_cache_key("discovery", cfg))
    if doc is None:
        doc = _http(cfg.issuer + "/.well-known/openid-configuration")
        if str(doc.get("issuer", "")).rstrip("/") != cfg.issuer:
            raise OidcError("provider", "discovery document names a different issuer")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not str(doc.get(field, "")).strip():
                raise OidcError("provider", f"discovery document lacks {field}")
        cache.set(_cache_key("discovery", cfg), doc, DISCOVERY_TTL)
    return doc


def _jwks(cfg, doc, refresh=False):
    key = _cache_key("jwks", cfg)
    keys = None if refresh else cache.get(key)
    if keys is None:
        keys = _http(doc["jwks_uri"]).get("keys") or []
        cache.set(key, keys, DISCOVERY_TTL)
    return keys


def _signing_key(cfg, doc, kid):
    # A key rollover shows up as an unknown kid: refetch once, then give up.
    for refresh in (False, True):
        keys = _jwks(cfg, doc, refresh=refresh)
        for k in keys:
            if k.get("use", "sig") != "sig":
                continue
            if k.get("kid") == kid or (kid is None and len(keys) == 1):
                try:
                    return jwt.PyJWK(k).key
                except jwt.PyJWTError as exc:
                    raise OidcError("token", f"provider key unusable: {exc}")
    raise OidcError("token", "the ID token was signed with a key the provider does not publish")


def _same(a, b):
    """Constant-time equality that tolerates any text (compare_digest wants
    ASCII str or bytes; a state parameter is whatever the URL carried)."""
    return secrets.compare_digest(str(a or "").encode("utf-8"), str(b or "").encode("utf-8"))


def _privileged(user):
    """Accounts the email match must never bind: the platform's own
    administrators by any route -- superuser, staff, or a role that manages
    users (that role can create a superuser-equivalent in one request)."""
    return bool(user.is_superuser or user.is_staff or user.can_manage_users)


def verify_id_token(cfg, doc, raw, nonce):
    try:
        header = jwt.get_unverified_header(raw)
    except jwt.PyJWTError as exc:
        raise OidcError("token", f"malformed ID token: {exc}")
    alg = header.get("alg")
    if alg not in ALGORITHMS:
        raise OidcError("token", f"unsupported signing algorithm {alg!r}")
    key = _signing_key(cfg, doc, header.get("kid"))
    try:
        # The issuer is checked below rather than by PyJWT: Auth0 and Entra
        # v1 publish "https://x/" with the slash, and the configured value
        # is normalised without it, so the comparison must normalise too.
        claims = jwt.decode(
            raw, key, algorithms=[alg], audience=cfg.client_id, leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_iss": False},
        )
    except jwt.PyJWTError as exc:
        raise OidcError("token", f"ID token rejected: {exc}")
    if str(claims.get("iss") or "").rstrip("/") != cfg.issuer:
        raise OidcError("token", "ID token issuer mismatch")
    if not nonce or not _same(claims.get("nonce"), nonce):
        raise OidcError("token", "nonce mismatch")
    return claims


# --------------------------------------------------------------------------- #
# The flow
# --------------------------------------------------------------------------- #
def _safe_next(path):
    path = str(path or "/")
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path[:512]


def redirect_uri(request, cfg):
    return cfg.redirect_uri or request.build_absolute_uri("/api/auth/oidc/callback/")


def begin(request, next_path="/"):
    """Park the flow secrets in the session and return the provider URL."""
    cfg = config()
    if not cfg.enabled:
        raise OidcError("disabled")
    doc = discovery(cfg)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    request.session[SESSION_KEY] = {
        "state": state, "nonce": nonce, "verifier": verifier,
        "next": _safe_next(next_path), "ts": int(time.time()),
    }
    request.session.modified = True
    params = {
        "response_type": "code", "client_id": cfg.client_id,
        "redirect_uri": redirect_uri(request, cfg), "scope": cfg.scopes,
        "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    endpoint = doc["authorization_endpoint"]
    return endpoint + ("&" if "?" in endpoint else "?") + urllib.parse.urlencode(params)


def mfa_asserted(claims):
    """Did the provider say a second factor was used? OIDC puts it in ``amr``
    (and sometimes ``acr``); the accepted values are SSO_MFA_ASSERTIONS."""
    accepted = set(getattr(settings, "SSO_MFA_ASSERTIONS", []) or [])
    amr = claims.get("amr") or []
    if isinstance(amr, str):
        amr = [amr]
    if any(str(a) in accepted for a in amr):
        return True
    return bool(claims.get("acr")) and str(claims.get("acr")) in accepted


def step_up_needed(user, asserted):
    """Apply SSO_STEP_UP. Returns True when the local authenticator must be
    asked for before tokens are issued; raises when the sign-in is refused."""
    policy = str(getattr(settings, "SSO_STEP_UP", "if_enrolled") or "if_enrolled")
    if policy == "off" or asserted:
        return False
    if user.mfa_enabled:   # an authenticator app or a passkey
        return True
    if policy == "required":
        raise OidcError("mfa_required", f"{user.get_username()} has no authenticator and the "
                                        "provider asserted no second factor")
    return False


def complete(request):
    """Finish the sign-in. Returns ``(user, how, next_path, mfa_asserted)``."""
    cfg = config()
    if not cfg.enabled:
        raise OidcError("disabled")
    flow = request.session.pop(SESSION_KEY, None)
    request.session.modified = True
    if not flow or int(time.time()) - int(flow.get("ts", 0)) > FLOW_TTL:
        raise OidcError("state", "no sign-in in progress, or it expired")
    if request.GET.get("error"):
        raise OidcError("denied", str(request.GET.get("error_description") or request.GET["error"])[:200])
    state, code = str(request.GET.get("state") or ""), str(request.GET.get("code") or "")
    if not state or not code or not _same(state, flow.get("state")):
        raise OidcError("state", "state mismatch")

    doc = discovery(cfg)
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri(request, cfg),
        "client_id": cfg.client_id, "client_secret": cfg.client_secret,
        "code_verifier": flow["verifier"],
    }).encode("ascii")
    tokens = _http(doc["token_endpoint"], data=body,
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
    raw = tokens.get("id_token") if isinstance(tokens, dict) else None
    if not raw:
        raise OidcError("token", "no id_token in the token response")
    claims = verify_id_token(cfg, doc, raw, flow.get("nonce"))

    # Some providers keep email out of the ID token; ask userinfo, and only
    # trust an answer that is about the same subject.
    if not claims.get("email") and tokens.get("access_token") and doc.get("userinfo_endpoint"):
        try:
            info = _http(doc["userinfo_endpoint"],
                         headers={"Authorization": "Bearer " + str(tokens["access_token"])})
        except OidcError:
            info = {}
        if isinstance(info, dict) and info.get("sub") == claims.get("sub"):
            for field in ("email", "email_verified", "name", "given_name", "family_name"):
                if info.get(field) is not None and claims.get(field) is None:
                    claims[field] = info[field]

    user, how = resolve_user(claims, cfg)
    return user, how, flow.get("next") or "/", mfa_asserted(claims)


# --------------------------------------------------------------------------- #
# Identity -> account
# --------------------------------------------------------------------------- #
def _names(claims):
    given = str(claims.get("given_name") or "").strip()
    family = str(claims.get("family_name") or "").strip()
    if not (given or family) and claims.get("name"):
        parts = str(claims["name"]).strip().split(" ", 1)
        given, family = parts[0], (parts[1] if len(parts) > 1 else "")
    return given[:150], family[:150]


def _unique_username(base):
    User = get_user_model()
    base = (base or "sso-user")[:140]
    candidate = base
    n = 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@transaction.atomic
def resolve_user(claims, cfg):
    User = get_user_model()
    issuer = str(claims.get("iss") or "")
    subject = str(claims.get("sub") or "")
    if not subject:
        raise OidcError("token", "ID token has no subject")
    email = str(claims.get("email") or "").strip().lower()[:254]

    identity = (OidcIdentity.objects.select_related("user__role")
                .filter(issuer=issuer, subject=subject).first())
    if identity is not None:
        if not identity.user.is_active:
            raise OidcError("inactive")
        # Re-checked on every sign-in, not just when the link was made: a
        # user promoted to administrator since then must go back to their
        # password until an operator re-affirms the link.
        if _privileged(identity.user) and not identity.privileged_ok:
            raise OidcError("privileged", f"{identity.user.get_username()} is privileged and the "
                                          "link was not made with --allow-privileged")
        identity.last_login_at = timezone.now()
        if email and identity.email != email:
            identity.email = email
        identity.save(update_fields=["last_login_at", "email"])
        return identity.user, "linked identity"

    if not email:
        raise OidcError("no_email")
    if cfg.require_verified_email and claims.get("email_verified") is not True:
        raise OidcError("unverified_email")
    domain = email.rsplit("@", 1)[-1]
    if cfg.allowed_domains and domain not in cfg.allowed_domains:
        raise OidcError("domain", f"{domain} is not an allowed domain")

    if cfg.link_by_email:
        matches = list(User.objects.filter(email__iexact=email)[:2])
        if len(matches) > 1:
            raise OidcError("ambiguous_email")
        if len(matches) == 1:
            user = matches[0]
            if _privileged(user):
                raise OidcError("privileged", f"refused to link {user.get_username()} by email")
            if not user.is_active:
                raise OidcError("inactive")
            OidcIdentity.objects.create(user=user, issuer=issuer, subject=subject, email=email,
                                        last_login_at=timezone.now())
            return user, "linked by verified email"

    if cfg.auto_provision:
        role = Role.objects.filter(name__iexact=cfg.default_role).first()
        if role is None:
            raise OidcError("role", f"role {cfg.default_role!r} does not exist")
        if role.can_manage_users:
            raise OidcError("role", f"default role {role.name!r} can manage users; refusing to provision")
        given, family = _names(claims)
        user = User.objects.create_user(
            username=_unique_username(email), email=email, first_name=given, last_name=family,
            role=role, is_staff=False, is_superuser=False,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        OidcIdentity.objects.create(user=user, issuer=issuer, subject=subject, email=email,
                                    last_login_at=timezone.now())
        return user, f"provisioned as {role.name}"

    raise OidcError("unknown_user", f"no account for {email}")


# --------------------------------------------------------------------------- #
# Tickets: the callback is a browser navigation; the SPA needs the tokens
# --------------------------------------------------------------------------- #
TICKET_KEY = "oidc_ticket"
STEP_UP_TTL = 300       # long enough to find the phone
STEP_UP_TRIES = 5


def issue_ticket(request, user, mfa_pending=False):
    """A one-time ticket, kept (hashed) in the browser session that ran the
    flow. The session store is shared by every worker, which the default
    per-process cache is not, and a ticket lifted out of the redirect URL is
    useless in any other browser. With ``mfa_pending`` the ticket is only
    redeemable together with a valid local authenticator code."""
    ticket = secrets.token_urlsafe(32)
    request.session[TICKET_KEY] = {
        "hash": hashlib.sha256(ticket.encode("ascii")).hexdigest(),
        "user": user.pk, "exp": int(time.time()) + (STEP_UP_TTL if mfa_pending else TICKET_TTL),
        "mfa": bool(mfa_pending), "tries": 0,
    }
    request.session.modified = True
    return ticket


def _drop_ticket(request):
    request.session.pop(TICKET_KEY, None)
    request.session.modified = True


def redeem_ticket(request, ticket, otp=None, passkey=None):
    data = request.session.get(TICKET_KEY)
    if not data:
        raise OidcError("state", "no sign-in ticket in this browser session, or it was already used")
    if int(time.time()) > int(data.get("exp", 0)):
        _drop_ticket(request)
        raise OidcError("state", "ticket expired")
    presented = hashlib.sha256(str(ticket or "")[:256].encode("utf-8")).hexdigest()
    if not _same(presented, data.get("hash")):
        _drop_ticket(request)
        raise OidcError("state", "ticket mismatch")
    user = get_user_model().objects.filter(pk=data["user"], is_active=True).first()
    if user is None:
        _drop_ticket(request)
        raise OidcError("inactive")
    if data.get("mfa"):
        if otp is None and passkey is None:
            raise StepUpRequired(user)
        if otp is not None:
            device = getattr(user, "mfa_device", None)
            ok = device is not None and device.enabled and device.verify(str(otp)[:64])
            why = "wrong code"
        else:
            from . import passkeys
            try:
                passkeys.finish_login(user, request, passkey)
                ok = True
            except passkeys.PasskeyRefused as exc:
                ok, why = False, f"passkey refused ({exc.code})"
        if not ok:
            data["tries"] = int(data.get("tries", 0)) + 1
            if data["tries"] >= STEP_UP_TRIES:
                _drop_ticket(request)
                raise OidcError("state", "too many wrong codes; start the sign-in again")
            request.session[TICKET_KEY] = data
            request.session.modified = True
            raise OidcError("mfa_invalid", f"{why} ({data['tries']}/{STEP_UP_TRIES})")
    _drop_ticket(request)
    return user


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def audit(request, user, ok, detail):
    try:
        AuditLog.objects.create(
            user=user, action="login" if ok else "login_failed", object_type="auth",
            object_id=str(user.pk) if user else "", detail=str(detail)[:255],
            ip_address=_client_ip(request),
        )
    except Exception:  # never let bookkeeping break sign-in
        log.exception("Failed to record an SSO event")
