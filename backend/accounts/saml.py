"""
Single sign-on over SAML 2.0 (SP-initiated, HTTP-Redirect out, HTTP-POST back).

Same posture as OIDC (accounts/oidc.py): the provider is configured from the
environment only, the identity-to-account rules are the same code, and the
tokens reach the SPA through the same one-time ticket. What SAML adds is XML,
and XML is where SAML deployments get broken, so the rules here are short:

* The provider's signing certificate from the environment is the only trust
  anchor. No metadata fetch, no certificate from inside the message.
* Only the element the signature actually covers is read. A Response whose
  signature covers one assertion and which carries a second, unsigned
  assertion (the classic wrapping attack) yields nothing from the second.
* Parsing resolves no entities, loads nothing from the network and refuses
  DTDs; a response over 256 KB is refused before it is parsed.
* The flow state (request id, relay, where to go next) travels in a signed,
  HttpOnly cookie rather than the session: the provider's POST back to us is
  cross-site, and a SameSite=Lax session cookie is not sent on it. The
  cookie is SameSite=None; Secure, so it is -- and the assertion's
  InResponseTo must match it.
* An assertion id is accepted once. Replays are refused from a shared table,
  not a per-process cache.

Only HTTP-POST binding responses with a bearer subject are accepted; requests
are not signed (the providers that require signed requests are rare, and a
signing key would be one more secret to keep).
"""
import base64
import datetime as dt
import secrets
import time
import zlib
from dataclasses import dataclass
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

from django.conf import settings
from django.core import signing
from django.utils import timezone
from lxml import etree
from signxml import SignatureConfiguration, SignatureMethod, XMLVerifier

from .oidc import Config as OidcConfig
from .oidc import OidcError, _safe_next, _same, resolve_user

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
EMAIL_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"

FLOW_COOKIE = "conformiti_saml"
FLOW_TTL = 600
SKEW = 180                # seconds of clock drift tolerated on NotBefore/NotOnOrAfter
MAX_RESPONSE = 256 * 1024

ASYMMETRIC = frozenset({
    SignatureMethod.RSA_SHA256, SignatureMethod.RSA_SHA384, SignatureMethod.RSA_SHA512,
    SignatureMethod.ECDSA_SHA256, SignatureMethod.ECDSA_SHA384, SignatureMethod.ECDSA_SHA512,
    SignatureMethod.SHA256_RSA_MGF1, SignatureMethod.SHA384_RSA_MGF1, SignatureMethod.SHA512_RSA_MGF1,
})

# Attribute names providers use for the pieces we need, in order of preference.
EMAIL_ATTRS = (
    "email", "mail", "emailaddress", "emailAddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "urn:oid:0.9.2342.19200300.100.1.3",
)
GIVEN_ATTRS = ("givenName", "given_name", "firstName", "first_name",
               "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname", "urn:oid:2.5.4.42")
FAMILY_ATTRS = ("sn", "surname", "family_name", "lastName", "last_name",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname", "urn:oid:2.5.4.4")
NAME_ATTRS = ("displayName", "name", "cn",
              "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")
AUTHN_METHOD_ATTRS = ("http://schemas.microsoft.com/claims/authnmethodsreferences", "authnmethodsreferences")


@dataclass(frozen=True)
class Config:
    idp_entity_id: str
    sso_url: str
    cert: str
    sp_entity_id: str
    acs_url: str
    label: str
    email_attribute: str
    allowed_domains: tuple
    auto_provision: bool
    default_role: str
    link_by_email: bool

    @property
    def enabled(self):
        return bool(self.idp_entity_id and self.sso_url and self.cert)

    def as_oidc(self):
        """The account-resolution policy in the shape resolve_user() reads.
        A signed assertion is the provider vouching for the address, so the
        email counts as verified."""
        return OidcConfig(
            issuer=self.idp_entity_id, client_id="", client_secret="", scopes="", label=self.label,
            redirect_uri="", allowed_domains=self.allowed_domains, auto_provision=self.auto_provision,
            default_role=self.default_role, link_by_email=self.link_by_email, require_verified_email=False,
        )


def config():
    cert = str(getattr(settings, "SAML_IDP_CERT", "") or "").strip()
    if cert and "BEGIN CERTIFICATE" not in cert:
        body = "".join(cert.split())
        cert = "-----BEGIN CERTIFICATE-----\n" + "\n".join(
            body[i:i + 64] for i in range(0, len(body), 64)) + "\n-----END CERTIFICATE-----"
    cert = cert.replace("\\n", "\n")
    domains = getattr(settings, "SAML_ALLOWED_DOMAINS", []) or []
    return Config(
        idp_entity_id=str(getattr(settings, "SAML_IDP_ENTITY_ID", "") or "").strip(),
        sso_url=str(getattr(settings, "SAML_IDP_SSO_URL", "") or "").strip(),
        cert=cert,
        sp_entity_id=str(getattr(settings, "SAML_SP_ENTITY_ID", "") or "").strip(),
        acs_url=str(getattr(settings, "SAML_ACS_URL", "") or "").strip(),
        label=str(getattr(settings, "SAML_LABEL", "Sign in with SAML") or "Sign in with SAML"),
        email_attribute=str(getattr(settings, "SAML_EMAIL_ATTRIBUTE", "") or "").strip(),
        allowed_domains=tuple(d.strip().lower().lstrip("@") for d in domains if d and d.strip()),
        auto_provision=bool(getattr(settings, "SAML_AUTO_PROVISION", False)),
        default_role=str(getattr(settings, "SAML_DEFAULT_ROLE", "Viewer") or "Viewer"),
        link_by_email=bool(getattr(settings, "SAML_LINK_BY_EMAIL", True)),
    )


def sp_entity_id(request, cfg):
    return cfg.sp_entity_id or request.build_absolute_uri("/api/auth/saml/metadata/")


def acs_url(request, cfg):
    return cfg.acs_url or request.build_absolute_uri("/api/auth/saml/acs/")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(text):
    text = str(text or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        value = dt.datetime.fromisoformat(text)
    except ValueError:
        raise OidcError("token", f"unreadable timestamp {text!r} in the assertion")
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value


# --------------------------------------------------------------------------- #
# Outbound: the AuthnRequest
# --------------------------------------------------------------------------- #
def begin(request, next_path="/"):
    """Build the AuthnRequest and the flow cookie; return (url, cookie_value)."""
    cfg = config()
    if not cfg.enabled:
        raise OidcError("disabled")
    request_id = "_" + secrets.token_hex(20)
    relay = secrets.token_urlsafe(24)
    sp, acs = sp_entity_id(request, cfg), acs_url(request, cfg)
    xml = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID={quoteattr(request_id)} Version="2.0" IssueInstant={quoteattr(_iso(_now()))} '
        f'Destination={quoteattr(cfg.sso_url)} ProtocolBinding={quoteattr(POST_BINDING)} '
        f'AssertionConsumerServiceURL={quoteattr(acs)}>'
        f'<saml:Issuer>{escape(sp)}</saml:Issuer>'
        f'<samlp:NameIDPolicy Format={quoteattr(EMAIL_FORMAT)} AllowCreate="true"/>'
        '</samlp:AuthnRequest>'
    )
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)      # raw DEFLATE, as the binding wants
    packed = base64.b64encode(deflater.compress(xml.encode("utf-8")) + deflater.flush()).decode("ascii")
    url = cfg.sso_url + ("&" if "?" in cfg.sso_url else "?") + urlencode(
        {"SAMLRequest": packed, "RelayState": relay})
    cookie = signing.dumps(
        {"id": request_id, "relay": relay, "next": _safe_next(next_path), "sp": sp, "acs": acs},
        salt="saml-flow", compress=True,
    )
    return url, cookie


def read_flow(request):
    """The flow this browser started, or None."""
    raw = request.COOKIES.get(FLOW_COOKIE)
    if not raw:
        return None
    try:
        return signing.loads(raw, salt="saml-flow", max_age=FLOW_TTL)
    except signing.BadSignature:
        return None


# --------------------------------------------------------------------------- #
# Inbound: the Response
# --------------------------------------------------------------------------- #
def _parse(raw):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                             huge_tree=False, remove_comments=True, remove_pis=True)
    try:
        root = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as exc:
        raise OidcError("token", f"the SAML response is not well-formed XML: {exc}")
    if root.getroottree().docinfo.doctype:
        raise OidcError("token", "DTDs are not accepted in a SAML response")
    if etree.QName(root) != etree.QName(NS["samlp"], "Response"):
        raise OidcError("token", "the message is not a samlp:Response")
    return root


def _signed_assertion(root, cfg):
    """Verify every signature against the provider's certificate and return
    the one assertion the signed content vouches for."""
    try:
        results = XMLVerifier().verify(
            root, x509_cert=cfg.cert,
            expect_config=SignatureConfiguration(
                signature_methods=ASYMMETRIC, ignore_ambiguous_key_info=True),
        )
    except Exception as exc:  # signxml raises several classes; none is acceptable
        raise OidcError("token", f"signature rejected: {exc.__class__.__name__}: {exc}")
    for result in (results if isinstance(results, list) else [results]):
        signed = result.signed_xml
        if signed is None:
            continue
        name = etree.QName(signed).localname
        if name == "Response":
            assertions = signed.findall("saml:Assertion", NS)
            if len(assertions) == 1:
                return assertions[0]
            raise OidcError("token", f"a signed Response must carry exactly one assertion, not {len(assertions)}")
        if name == "Assertion":
            return signed
    raise OidcError("token", "the signature does not cover an assertion")


def _attributes(assertion):
    out = {}
    for attr in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        name = attr.get("Name") or ""
        values = [(v.text or "").strip() for v in attr.findall("saml:AttributeValue", NS)]
        out[name] = [v for v in values if v]
        friendly = attr.get("FriendlyName")
        if friendly and friendly not in out:
            out[friendly] = out[name]
    return out


def _first(attrs, names):
    for name in names:
        if attrs.get(name):
            return attrs[name][0]
    return ""


def complete(request, flow):
    """Validate the posted Response. Returns (user, how, next_path, mfa_asserted)."""
    cfg = config()
    if not cfg.enabled:
        raise OidcError("disabled")
    if flow is None:
        raise OidcError("state", "no sign-in in progress in this browser, or it expired")
    if not _same(request.POST.get("RelayState", ""), flow.get("relay")):
        raise OidcError("state", "relay state mismatch")
    encoded = request.POST.get("SAMLResponse", "")
    if len(encoded) > MAX_RESPONSE * 4 // 3 + 4:
        raise OidcError("token", "the SAML response is too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise OidcError("token", "the SAML response is not valid base64")
    if len(raw) > MAX_RESPONSE:
        raise OidcError("token", "the SAML response is too large")

    root = _parse(raw)
    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or status.get("Value") != SUCCESS:
        message = root.findtext("samlp:Status/samlp:StatusMessage", default="", namespaces=NS)
        raise OidcError("denied", (message or (status.get("Value") if status is not None else "no status"))[:200])

    assertion = _signed_assertion(root, cfg)
    now = _now()

    issuer = (assertion.findtext("saml:Issuer", default="", namespaces=NS) or "").strip()
    if issuer != cfg.idp_entity_id:
        raise OidcError("token", "assertion issuer mismatch")
    response_to = root.get("InResponseTo")
    if response_to and not _same(response_to, flow["id"]):
        raise OidcError("state", "the response answers a different request")
    destination = root.get("Destination")
    if destination and destination != flow["acs"]:
        raise OidcError("token", "the response was meant for another destination")

    conditions = assertion.find("saml:Conditions", NS)
    if conditions is None:
        raise OidcError("token", "assertion has no conditions")
    not_before = _parse_time(conditions.get("NotBefore"))
    not_after = _parse_time(conditions.get("NotOnOrAfter"))
    skew = dt.timedelta(seconds=SKEW)
    if not_before and now + skew < not_before:
        raise OidcError("token", "assertion is not yet valid")
    if not_after and now - skew >= not_after:
        raise OidcError("token", "assertion has expired")
    audiences = [(a.text or "").strip() for a in conditions.findall("saml:AudienceRestriction/saml:Audience", NS)]
    if not audiences or flow["sp"] not in audiences:
        raise OidcError("token", "we are not the audience of this assertion")

    subject = assertion.find("saml:Subject", NS)
    if subject is None:
        raise OidcError("token", "assertion has no subject")
    name_id = (subject.findtext("saml:NameID", default="", namespaces=NS) or "").strip()
    confirmed = False
    for sc in subject.findall("saml:SubjectConfirmation", NS):
        if sc.get("Method") != BEARER:
            continue
        data = sc.find("saml:SubjectConfirmationData", NS)
        if data is None:
            continue
        if not _same(data.get("InResponseTo", ""), flow["id"]):
            continue
        recipient = data.get("Recipient")
        if recipient and recipient != flow["acs"]:
            continue
        expiry = _parse_time(data.get("NotOnOrAfter"))
        if expiry and now - skew >= expiry:
            continue
        confirmed = True
        break
    if not confirmed:
        raise OidcError("state", "no bearer confirmation answers our request")

    assertion_id = assertion.get("ID") or ""
    if not assertion_id:
        raise OidcError("token", "assertion has no ID")
    _refuse_replay(assertion_id, not_after or now + dt.timedelta(hours=1))

    attrs = _attributes(assertion)
    email = ""
    if cfg.email_attribute:
        email = _first(attrs, (cfg.email_attribute,))
    if not email:
        email = _first(attrs, EMAIL_ATTRS)
    if not email and "@" in name_id:
        email = name_id
    if not name_id:
        name_id = email
    if not name_id:
        raise OidcError("token", "assertion names nobody: no NameID and no email attribute")

    contexts = [(c.text or "").strip() for c in assertion.findall(
        "saml:AuthnStatement/saml:AuthnContext/saml:AuthnContextClassRef", NS)]
    for name in AUTHN_METHOD_ATTRS:
        contexts.extend(attrs.get(name, []))
    asserted = set(getattr(settings, "SSO_MFA_ASSERTIONS", []) or [])
    mfa_asserted = any(c in asserted for c in contexts)

    claims = {
        "iss": cfg.idp_entity_id, "sub": name_id, "email": email.lower(), "email_verified": bool(email),
        "given_name": _first(attrs, GIVEN_ATTRS), "family_name": _first(attrs, FAMILY_ATTRS),
        "name": _first(attrs, NAME_ATTRS),
    }
    user, how = resolve_user(claims, cfg.as_oidc())
    return user, how, flow.get("next") or "/", mfa_asserted


def _refuse_replay(assertion_id, expires_at):
    from django.db import IntegrityError, transaction

    from .models import SsoAssertion

    SsoAssertion.objects.filter(expires_at__lt=timezone.now()).delete()
    try:
        # A savepoint, so the unique clash does not poison an outer transaction.
        with transaction.atomic():
            SsoAssertion.objects.create(assertion_id=assertion_id[:255], expires_at=expires_at)
    except IntegrityError:
        raise OidcError("state", "this assertion has already been used")


# --------------------------------------------------------------------------- #
# Our metadata, for the provider's administrator
# --------------------------------------------------------------------------- #
def metadata_xml(request):
    cfg = config()
    sp, acs = sp_entity_id(request, cfg), acs_url(request, cfg)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<md:EntityDescriptor xmlns:md="{NS["md"]}" entityID={quoteattr(sp)}>'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<md:NameIDFormat>{EMAIL_FORMAT}</md:NameIDFormat>'
        f'<md:AssertionConsumerService Binding={quoteattr(POST_BINDING)} Location={quoteattr(acs)} index="0" isDefault="true"/>'
        '</md:SPSSODescriptor></md:EntityDescriptor>\n'
    )
