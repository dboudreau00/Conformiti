"""
SAML 2.0 sign-in, fully offline: a self-signed certificate stands in for the
provider, responses are signed with signxml exactly as an IdP would sign them,
and every check on the way in is exercised with a response that fails it.
"""
import base64
import datetime as dt
import secrets
import zlib
from unittest import mock
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core import signing
from django.test import override_settings
from lxml import etree
from signxml import CanonicalizationMethod, DigestAlgorithm, SignatureMethod, XMLSigner

from accounts import mfa as mfa_lib
from accounts import saml
from accounts.models import MfaDevice, OidcIdentity, SsoAssertion
from audit.models import AuditLog
from testutils import APITestBase

IDP = "https://idp.example/saml"
SSO = "https://idp.example/sso"


def _selfsigned():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=365)).sign(key, hashes.SHA256()))
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, cert_pem


KEY, CERT = _selfsigned()
OTHER_KEY, OTHER_CERT = _selfsigned()
SETTINGS = dict(SAML_IDP_ENTITY_ID=IDP, SAML_IDP_SSO_URL=SSO, SAML_IDP_CERT=CERT, SAML_LABEL="Corp SAML",
                SAML_ALLOWED_DOMAINS=[], SAML_AUTO_PROVISION=False, SAML_DEFAULT_ROLE="Viewer",
                SAML_LINK_BY_EMAIL=True, SAML_EMAIL_ATTRIBUTE="", SSO_STEP_UP="if_enrolled", DEBUG=False)

NS = saml.NS


class FakeIdp:
    """Builds signed Responses the way a provider would, with knobs for every
    thing the consumer must refuse."""

    def __init__(self, flow):
        self.flow = flow
        self.key, self.cert = KEY, CERT
        self.email = "val@example.com"
        self.name_id = "val@example.com"
        self.issuer = IDP
        self.audience = flow["sp"]
        self.recipient = flow["acs"]
        self.in_response_to = flow["id"]
        self.not_after = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
        self.not_before = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        self.context = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
        self.attrs = {"givenName": "Val", "sn": "Viewer"}
        # Unique per response, as a real provider's would be: the consumer
        # remembers every id it has seen, refused sign-ins included.
        self.assertion_id = "_a" + secrets.token_hex(15)
        self.sign = "response"       # response | assertion | none
        self.status = "urn:oasis:names:tc:SAML:2.0:status:Success"
        self.extra_assertion = None

    def _t(self, when):
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")

    def assertion_xml(self, assertion_id=None, email=None, name_id=None):
        attrs = "".join(
            f'<saml:Attribute Name="{k}"><saml:AttributeValue>{v}</saml:AttributeValue></saml:Attribute>'
            for k, v in {**self.attrs, "email": email or self.email}.items())
        return (
            f'<saml:Assertion xmlns:saml="{NS["saml"]}" ID="{assertion_id or self.assertion_id}" '
            f'Version="2.0" IssueInstant="{self._t(self.not_before)}">'
            f'<saml:Issuer>{self.issuer}</saml:Issuer>'
            f'<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{name_id or self.name_id}</saml:NameID>'
            f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
            f'<saml:SubjectConfirmationData InResponseTo="{self.in_response_to}" Recipient="{self.recipient}" '
            f'NotOnOrAfter="{self._t(self.not_after)}"/></saml:SubjectConfirmation></saml:Subject>'
            f'<saml:Conditions NotBefore="{self._t(self.not_before)}" NotOnOrAfter="{self._t(self.not_after)}">'
            f'<saml:AudienceRestriction><saml:Audience>{self.audience}</saml:Audience></saml:AudienceRestriction>'
            f'</saml:Conditions>'
            f'<saml:AuthnStatement AuthnInstant="{self._t(self.not_before)}"><saml:AuthnContext>'
            f'<saml:AuthnContextClassRef>{self.context}</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>'
            f'<saml:AttributeStatement>{attrs}</saml:AttributeStatement>'
            f'</saml:Assertion>'
        )

    def response(self):
        signer = XMLSigner(signature_algorithm=SignatureMethod.RSA_SHA256, digest_algorithm=DigestAlgorithm.SHA256,
                           c14n_algorithm=CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0)
        assertion = etree.fromstring(self.assertion_xml())
        if self.sign == "assertion":
            assertion = signer.sign(assertion, key=self.key, cert=self.cert)
        root = etree.fromstring(
            f'<samlp:Response xmlns:samlp="{NS["samlp"]}" xmlns:saml="{NS["saml"]}" ID="_r{self.assertion_id[2:]}" '
            f'Version="2.0" IssueInstant="{self._t(self.not_before)}" Destination="{self.recipient}" '
            f'InResponseTo="{self.in_response_to}"><saml:Issuer>{self.issuer}</saml:Issuer>'
            f'<samlp:Status><samlp:StatusCode Value="{self.status}"/></samlp:Status></samlp:Response>')
        if self.extra_assertion is not None:
            root.append(etree.fromstring(self.extra_assertion))
        root.append(assertion)
        if self.sign == "response":
            root = signer.sign(root, key=self.key, cert=self.cert)
        return base64.b64encode(etree.tostring(root)).decode("ascii")


@override_settings(**SETTINGS)
class SamlFlowTests(APITestBase):
    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.viewer.email = "val@example.com"
        self.viewer.save()
        self.anon = self.client_class()

    def start(self):
        from django.core.cache import cache
        cache.clear()
        r = self.anon.get("/api/auth/saml/start/")
        self.assertEqual(r.status_code, 302, r.content[:200])
        raw = self.anon.cookies[saml.FLOW_COOKIE].value
        flow = signing.loads(raw, salt="saml-flow")
        query = parse_qs(urlparse(r["Location"]).query)
        return flow, query

    def post(self, idp, relay=None):
        return self.anon.post("/api/auth/saml/acs/", {
            "SAMLResponse": idp.response(), "RelayState": idp.flow["relay"] if relay is None else relay})

    def sign_in(self, tweak=None):
        flow, _ = self.start()
        idp = FakeIdp(flow)
        if tweak:
            tweak(idp)
        r = self.post(idp)
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:200])
        target = urlparse(r["Location"])
        params = parse_qs(target.query)
        self.assertNotIn("sso_error", params, params)
        return params["sso"][0]

    def refused(self, code, tweak=None, relay=None):
        flow, _ = self.start()
        idp = FakeIdp(flow)
        if tweak:
            tweak(idp)
        r = self.post(idp, relay=relay)
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"sso_error={code}", r["Location"], r["Location"])
        self.assertTrue(AuditLog.objects.filter(action="login_failed", detail__contains=f"({code})").exists())

    # ------------------------------------------------------------- start
    def test_start_sends_a_deflated_authn_request_and_a_flow_cookie(self):
        flow, query = self.start()
        raw = zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), -15)
        req = etree.fromstring(raw)
        self.assertEqual(req.get("Destination"), SSO)
        self.assertEqual(req.get("ID"), flow["id"])
        self.assertTrue(req.get("AssertionConsumerServiceURL").endswith("/api/auth/saml/acs/"))
        self.assertEqual(req.findtext("saml:Issuer", namespaces=NS), flow["sp"])
        self.assertEqual(query["RelayState"], [flow["relay"]])
        cookie = self.anon.cookies[saml.FLOW_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], "/api/auth/saml/")

    def test_config_and_metadata(self):
        r = self.anon.get("/api/auth/config/")
        self.assertEqual(r.data["saml"], {"enabled": True, "label": "Corp SAML"})
        r = self.anon.get("/api/auth/saml/metadata/")
        self.assertEqual(r.status_code, 200)
        md = etree.fromstring(r.content)
        self.assertTrue(md.get("entityID").endswith("/api/auth/saml/metadata/"))
        acs = md.find(".//md:AssertionConsumerService", NS)
        self.assertTrue(acs.get("Location").endswith("/api/auth/saml/acs/"))
        with override_settings(SAML_IDP_CERT=""):
            self.assertFalse(self.anon.get("/api/auth/config/").data["saml"]["enabled"])
            self.assertEqual(self.anon.get("/api/auth/saml/metadata/").status_code, 404)

    # -------------------------------------------------------- happy path
    def test_a_signed_response_links_by_email_and_signs_in(self):
        ticket = self.sign_in()
        self.assertEqual(OidcIdentity.objects.get(issuer=IDP, subject="val@example.com").user, self.viewer)
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        me = self.anon.get("/api/users/me/", HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        self.assertEqual(me.data["username"], "val")
        self.assertTrue(AuditLog.objects.filter(action="login", detail__contains="saml").exists())
        # The flow cookie is gone once used.
        self.assertFalse(self.anon.cookies.get(saml.FLOW_COOKIE, None) and self.anon.cookies[saml.FLOW_COOKIE].value)

    def test_an_assertion_level_signature_is_accepted(self):
        def tweak(idp):
            idp.sign = "assertion"
        self.assertTrue(self.sign_in(tweak))

    def test_names_come_from_attributes_and_provisioning_works(self):
        def tweak(idp):
            idp.email = idp.name_id = "new@corp.example"
        with override_settings(SAML_AUTO_PROVISION=True, SAML_ALLOWED_DOMAINS=["corp.example"]):
            self.sign_in(tweak)
        user = OidcIdentity.objects.get(subject="new@corp.example").user
        self.assertEqual((user.first_name, user.last_name, user.role.name), ("Val", "Viewer", "Viewer"))

    # ------------------------------------------------------------ refusals
    def test_unsigned_or_wrongly_signed_responses_are_refused(self):
        def unsigned(idp):
            idp.sign = "none"
        self.refused("token", unsigned)

        def other_key(idp):
            idp.key, idp.cert = OTHER_KEY, OTHER_CERT
        self.refused("token", other_key)

    def test_a_tampered_assertion_is_refused(self):
        flow, _ = self.start()
        idp = FakeIdp(flow)
        signed = base64.b64decode(idp.response())
        tampered = signed.replace(b"val@example.com", b"ada@example.com")
        r = self.anon.post("/api/auth/saml/acs/", {
            "SAMLResponse": base64.b64encode(tampered).decode(), "RelayState": flow["relay"]})
        self.assertIn("sso_error=token", r["Location"])
        self.assertFalse(OidcIdentity.objects.exists())

    def test_signature_wrapping_cannot_smuggle_a_second_assertion(self):
        self.admin.email = "ada@example.com"
        self.admin.save()

        def wrap(idp):
            # An unsigned assertion for the administrator placed before the signed one.
            idp.sign = "assertion"
            idp.extra_assertion = idp.assertion_xml(assertion_id="_evil" + "2" * 26,
                                                    email="ada@example.com", name_id="ada@example.com")
        ticket = self.sign_in(wrap)
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        me = self.anon.get("/api/users/me/", HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        self.assertEqual(me.data["username"], "val", "only the signed assertion counts")

        def two_in_signed_response(idp):
            idp.sign = "response"
            idp.extra_assertion = idp.assertion_xml(assertion_id="_two" + "3" * 26)
        self.refused("token", two_in_signed_response)

    def test_audience_destination_expiry_and_issuer_are_checked(self):
        def audience(idp):
            idp.audience = "https://someone-else.example/"
        self.refused("token", audience)

        def expired(idp):
            idp.not_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
        self.refused("token", expired)

        def future(idp):
            idp.not_before = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
        self.refused("token", future)

        def issuer(idp):
            idp.issuer = "https://evil.example/saml"
        self.refused("token", issuer)

        def recipient(idp):
            # Destination and Recipient both point elsewhere: the response
            # is not ours at all.
            idp.recipient = "https://evil.example/acs"
        self.refused("token", recipient)

    def test_state_relay_and_in_response_to_bind_the_browser(self):
        def other_request(idp):
            idp.in_response_to = "_notours"
        self.refused("state", other_request)
        self.refused("state", relay="wrong")
        # No flow cookie at all: nothing to answer.
        flow, _ = self.start()
        idp = FakeIdp(flow)
        self.anon.cookies.pop(saml.FLOW_COOKIE)
        r = self.post(idp)
        self.assertIn("sso_error=state", r["Location"])

    def test_an_assertion_is_accepted_once(self):
        flow, _ = self.start()
        idp = FakeIdp(flow)
        payload = idp.response()
        r = self.anon.post("/api/auth/saml/acs/", {"SAMLResponse": payload, "RelayState": flow["relay"]})
        self.assertNotIn("sso_error", r["Location"])
        self.assertTrue(SsoAssertion.objects.filter(assertion_id=idp.assertion_id).exists())
        # Same assertion again, with a fresh flow that it happens to answer.
        flow2, _ = self.start()
        idp2 = FakeIdp(flow2)
        idp2.assertion_id = idp.assertion_id
        r = self.post(idp2)
        self.assertIn("sso_error=state", r["Location"])

    def test_the_provider_declining_and_garbage_are_clean_refusals(self):
        def declined(idp):
            idp.status = "urn:oasis:names:tc:SAML:2.0:status:Responder"
        self.refused("denied", declined)
        flow, _ = self.start()
        r = self.anon.post("/api/auth/saml/acs/", {"SAMLResponse": "not base64!!", "RelayState": flow["relay"]})
        self.assertIn("sso_error=token", r["Location"])
        flow, _ = self.start()
        r = self.anon.post("/api/auth/saml/acs/", {
            "SAMLResponse": base64.b64encode(b"<!DOCTYPE x [<!ENTITY e 'e'>]><x>&e;</x>").decode(),
            "RelayState": flow["relay"]})
        self.assertIn("sso_error=token", r["Location"])

    def test_privileged_accounts_are_not_linked_by_email_here_either(self):
        self.admin.email = "ada@example.com"
        self.admin.save()

        def as_admin(idp):
            idp.email = idp.name_id = "ada@example.com"
        self.refused("privileged", as_admin)

    # ------------------------------------------------------------ step-up
    def _enrol(self, user):
        secret = mfa_lib.generate_secret()
        MfaDevice.objects.create(user=user, secret=secret, enabled=True)
        return secret

    def test_step_up_asks_for_the_local_code_when_the_provider_asserted_none(self):
        secret = self._enrol(self.viewer)
        ticket = self.sign_in()
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"mfa_required": True})
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket, "otp": "000000"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "mfa_invalid")
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket, "otp": mfa_lib.totp(secret)}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertTrue(AuditLog.objects.filter(detail__contains="step-up: second factor verified").exists())
        self.assertTrue(AuditLog.objects.filter(detail__contains="step-up pending").exists())

    def test_an_asserted_second_factor_skips_the_step_up(self):
        self._enrol(self.viewer)

        def asserted(idp):
            idp.context = "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken"
        ticket = self.sign_in(asserted)
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertIn("access", r.data)

    def test_too_many_wrong_codes_spend_the_ticket(self):
        self._enrol(self.viewer)
        ticket = self.sign_in()
        for _ in range(4):
            r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket, "otp": "111111"}, format="json")
            self.assertEqual(r.data["code"], "mfa_invalid")
        r = self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket, "otp": "111111"}, format="json")
        self.assertEqual(r.data["code"], "state")

    def test_required_policy_refuses_a_user_with_no_authenticator(self):
        with override_settings(SSO_STEP_UP="required"):
            self.refused("mfa_required")
            self._enrol(self.viewer)
            ticket = self.sign_in()
            self.assertEqual(self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").data,
                             {"mfa_required": True})
        with override_settings(SSO_STEP_UP="off"):
            ticket = self.sign_in()
            self.assertIn("access", self.anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json").data)
