"""
Passkeys (WebAuthn) as a second factor, fully offline: a fake authenticator
built on ``cryptography`` answers the browser's side of both ceremonies.

The tests that matter most are the counter ones. The 0.3.0 design for this
feature disabled a cloned key AND dropped the account to password-only; that
fail-open is what kept it off the roadmap, and ``CloneTests`` pins the fixed
behaviour: the key is refused, the factor stays required.
"""
import hashlib
import json
import secrets
import struct
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from django.test import override_settings
from rest_framework.test import APIClient

from accounts import mfa as mfa_lib
from accounts import webauthn as wa
from accounts.models import MfaDevice, WebAuthnChallenge, WebAuthnCredential
from audit.models import AuditLog
from testutils import PASSWORD, APITestBase

ORIGIN = "http://testserver"
RP_ID = "testserver"


class FakeAuthenticator:
    """Enough of a CTAP2 authenticator to answer create() and get()."""

    def __init__(self, algorithm=wa.ES256, counts=True, user_verified=True):
        self.algorithm = algorithm
        if algorithm == wa.ES256:
            self.key = ec.generate_private_key(ec.SECP256R1())
        elif algorithm == wa.RS256:
            self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        else:
            self.key = ed25519.Ed25519PrivateKey.generate()
        self.credential_id = secrets.token_bytes(32)
        self.counts = counts
        self.count = 0
        self.user_verified = user_verified
        self.rp_id = RP_ID
        self.origin = ORIGIN

    # --- pieces --------------------------------------------------------------
    def cose(self):
        pub = self.key.public_key()
        if self.algorithm == wa.ES256:
            n = pub.public_numbers()
            return {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        if self.algorithm == wa.RS256:
            n = pub.public_numbers()
            return {1: 3, 3: -257, -1: n.n.to_bytes(256, "big"), -2: n.e.to_bytes(3, "big")}
        from cryptography.hazmat.primitives import serialization
        raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return {1: 1, 3: -8, -1: 6, -2: raw}

    def flags(self, attested):
        f = wa.FLAG_UP
        if self.user_verified:
            f |= wa.FLAG_UV
        if attested:
            f |= wa.FLAG_AT
        return f

    def client_data(self, kind, challenge, origin=None):
        return json.dumps({"type": kind, "challenge": challenge,
                           "origin": origin or self.origin, "crossOrigin": False}).encode()

    def auth_data(self, attested, count, rp_id=None):
        raw = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        raw += bytes([self.flags(attested)]) + struct.pack(">I", count)
        if attested:
            raw += bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id
            raw += wa.cbor_dumps(self.cose())
        return raw

    def sign(self, data):
        if self.algorithm == wa.ES256:
            return self.key.sign(data, ec.ECDSA(hashes.SHA256()))
        if self.algorithm == wa.RS256:
            return self.key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        return self.key.sign(data)

    # --- ceremonies ----------------------------------------------------------
    def create(self, options, origin=None, rp_id=None, fmt="none"):
        client = self.client_data("webauthn.create", options["challenge"], origin)
        att = wa.cbor_dumps({"fmt": fmt, "attStmt": {}, "authData": self.auth_data(True, 0, rp_id)})
        cid = wa.b64url_encode(self.credential_id)
        return {"id": cid, "rawId": cid, "type": "public-key",
                "response": {"clientDataJSON": wa.b64url_encode(client),
                             "attestationObject": wa.b64url_encode(att),
                             "transports": ["internal"]}}

    def get(self, options, origin=None, rp_id=None, count=None, challenge=None):
        if count is None:
            if self.counts:
                self.count += 1
            count = self.count
        client = self.client_data("webauthn.get", challenge or options["challenge"], origin)
        auth = self.auth_data(False, count, rp_id)
        sig = self.sign(auth + hashlib.sha256(client).digest())
        cid = wa.b64url_encode(self.credential_id)
        return {"id": cid, "rawId": cid, "type": "public-key",
                "response": {"clientDataJSON": wa.b64url_encode(client),
                             "authenticatorData": wa.b64url_encode(auth),
                             "signature": wa.b64url_encode(sig), "userHandle": None}}


class PasskeyTestBase(APITestBase):
    def enrol(self, user, authenticator=None, name="Laptop", **create_kw):
        auth = authenticator or FakeAuthenticator()
        c = self.client_for(user)
        opts = c.post("/api/auth/webauthn/register/options/")
        self.assertEqual(opts.status_code, 200, opts.data)
        r = c.post("/api/auth/webauthn/register/", {
            "state": opts.data["state"], "name": name,
            "credential": auth.create(opts.data["options"], **create_kw),
        }, format="json")
        return auth, r

    def challenge(self, username):
        """The password step. Returns the 400 challenge response."""
        from django.core.cache import cache
        cache.clear()   # the per-IP login throttle, not the subject here
        r = APIClient().post("/api/auth/token/", {"username": username, "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertTrue(r.data.get("mfa_required"))
        return r

    def login_with(self, username, auth, **get_kw):
        r = self.challenge(username)
        assertion = auth.get(r.data["passkey"]["options"], **get_kw)
        return APIClient().post("/api/auth/token/", {
            "username": username, "password": PASSWORD,
            "passkey": {"state": r.data["passkey"]["state"], "credential": assertion},
        }, format="json")


# --------------------------------------------------------------------------- #
# The protocol module on its own
# --------------------------------------------------------------------------- #
class ProtocolTests(APITestBase):
    def test_cbor_round_trips_and_refuses_what_authenticators_never_send(self):
        value = {1: 2, 3: -7, -1: 1, -2: b"\x01" * 32, "fmt": "none", "list": [1, -2, "x", True, None]}
        self.assertEqual(wa.cbor_loads(wa.cbor_dumps(value)), value)
        # Indefinite lengths, duplicate keys, trailing bytes, tags and depth.
        for bad in (b"\x9f\x01\xff", b"\xa2\x01\x01\x01\x02", b"\x01\x02", b"\xc0\x01",
                    b"\x81" * 20 + b"\x01", b"\x1c", b"\x58\x05ab"):
            with self.assertRaises(wa.WebAuthnError):
                wa.cbor_loads(bad)

    def test_the_counter_rule(self):
        self.assertFalse(wa.counter_regressed(0, 0))     # a key that does not count
        self.assertFalse(wa.counter_regressed(0, 1))
        self.assertFalse(wa.counter_regressed(5, 6))
        self.assertTrue(wa.counter_regressed(5, 5))
        self.assertTrue(wa.counter_regressed(5, 4))
        self.assertTrue(wa.counter_regressed(5, 0))     # a counting key suddenly not counting

    def test_registration_binds_rp_id_origin_and_challenge(self):
        auth = FakeAuthenticator()
        opts = wa.registration_options(rp_id=RP_ID, rp_name="Conformiti", challenge="abc",
                                       user_pk=1, username="u", display_name="U", exclude=[])
        ok = wa.verify_registration(auth.create(opts), challenge="abc", rp_id=RP_ID, origins=[ORIGIN])
        self.assertEqual(ok.algorithm, wa.ES256)
        self.assertEqual(ok.credential_id, wa.b64url_encode(auth.credential_id))
        with self.assertRaises(wa.WebAuthnError) as cm:
            wa.verify_registration(auth.create(opts, origin="http://evil"), challenge="abc",
                                   rp_id=RP_ID, origins=[ORIGIN])
        self.assertEqual(cm.exception.code, "origin")
        with self.assertRaises(wa.WebAuthnError) as cm:
            wa.verify_registration(auth.create(opts, rp_id="other"), challenge="abc",
                                   rp_id=RP_ID, origins=[ORIGIN])
        self.assertEqual(cm.exception.code, "rp_id")
        with self.assertRaises(wa.WebAuthnError) as cm:
            wa.verify_registration(auth.create(opts), challenge="xyz", rp_id=RP_ID, origins=[ORIGIN])
        self.assertEqual(cm.exception.code, "challenge")
        # An attestation statement, if one arrives, is ignored rather than trusted.
        packed = wa.verify_registration(auth.create(opts, fmt="packed"), challenge="abc",
                                        rp_id=RP_ID, origins=[ORIGIN])
        self.assertEqual(packed.credential_id, ok.credential_id)

    def test_assertions_verify_for_every_supported_algorithm(self):
        for alg in wa.ALGORITHMS:
            auth = FakeAuthenticator(alg)
            reg = wa.verify_registration(auth.create({"challenge": "c1"}), challenge="c1",
                                         rp_id=RP_ID, origins=[ORIGIN])
            self.assertEqual(reg.algorithm, alg)
            got = wa.verify_authentication(auth.get({"challenge": "c2"}), challenge="c2", rp_id=RP_ID,
                                           origins=[ORIGIN], public_key_der=reg.public_key_der,
                                           algorithm=alg)
            self.assertEqual(got.sign_count, 1)
            # A signature from a different key of the same kind does not verify.
            other = FakeAuthenticator(alg)
            other.credential_id = auth.credential_id
            with self.assertRaises(wa.WebAuthnError) as cm:
                wa.verify_authentication(other.get({"challenge": "c3"}), challenge="c3", rp_id=RP_ID,
                                         origins=[ORIGIN], public_key_der=reg.public_key_der,
                                         algorithm=alg)
            self.assertEqual(cm.exception.code, "signature")

    def test_a_key_whose_type_disagrees_with_its_algorithm_is_refused(self):
        cose = FakeAuthenticator(wa.ES256).cose()
        cose[3] = wa.RS256
        with self.assertRaises(wa.WebAuthnError):
            wa.cose_to_public_key(cose)
        cose = FakeAuthenticator(wa.ES256).cose()
        cose[3] = -36    # ES512: not offered, not accepted
        with self.assertRaises(wa.WebAuthnError):
            wa.cose_to_public_key(cose)


# --------------------------------------------------------------------------- #
# Enrolment and sign-in through the API
# --------------------------------------------------------------------------- #
class EnrolAndLoginTests(PasskeyTestBase):
    def test_enrol_then_the_password_alone_is_a_challenge_and_the_passkey_completes_it(self):
        auth, r = self.enrol(self.manager)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["name"], "Laptop")
        self.assertEqual(r.data["algorithm"], "ES256")
        self.assertTrue(r.data["factors"]["passkey"])
        self.assertTrue(AuditLog.objects.filter(action="mfa", detail__contains="passkey enrolled: Laptop").exists())
        # The account now has a second factor, and says so.
        me = self.client_for(self.manager).get("/api/users/me/").data
        self.assertTrue(me["mfa_enabled"])
        status = self.client_for(self.manager).get("/api/auth/mfa/status/").data
        self.assertEqual((status["passkeys"], status["second_factor"], status["enabled"]), (1, True, False))

        r = self.challenge("mia")
        self.assertEqual(r.data["factors"],
                         {"totp": False, "passkey": True, "passkey_suspect": 0, "backup_codes": True})
        options = r.data["passkey"]["options"]
        self.assertEqual(options["rpId"], RP_ID)
        self.assertEqual(options["allowCredentials"][0]["id"], wa.b64url_encode(auth.credential_id))
        self.assertEqual(options["allowCredentials"][0]["transports"], ["internal"])
        self.assertNotIn("access", r.data)
        # No cookies and no tokens on the challenge step.
        self.assertEqual(r.cookies, {})

        ok = self.login_with("mia", auth)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertIn("access", ok.data)
        row = WebAuthnCredential.objects.get(user=self.manager)
        self.assertEqual(row.sign_count, 1)
        self.assertIsNotNone(row.last_used_at)
        self.assertTrue(AuditLog.objects.filter(action="login", detail="signed in: mia").exists())

    def test_the_challenge_carries_integers_intact(self):
        """The login response must not go through DRF's error-detail
        stringification: the browser needs real numbers in pubKeyCredParams
        and timeout."""
        self.enrol(self.owner)
        r = self.challenge("owen")
        self.assertIs(r.data["mfa_required"], True)
        self.assertIsInstance(r.data["passkey"]["options"]["timeout"], int)
        body = json.loads(r.content)
        self.assertIs(body["mfa_required"], True)
        self.assertEqual(body["passkey"]["options"]["timeout"], 120000)

    def test_registration_options_carry_the_right_shape(self):
        c = self.client_for(self.owner)
        opts = c.post("/api/auth/webauthn/register/options/").data["options"]
        self.assertEqual(opts["rp"], {"id": RP_ID, "name": "Conformiti"})
        self.assertEqual([p["alg"] for p in opts["pubKeyCredParams"]], [-7, -257, -8])
        self.assertEqual(opts["attestation"], "none")
        self.assertEqual(opts["user"]["name"], "owen")
        self.assertNotIn("@", opts["user"]["id"])   # opaque, never the email

    def test_a_challenge_answers_once_and_expires(self):
        auth = FakeAuthenticator()
        c = self.client_for(self.owner)
        opts = c.post("/api/auth/webauthn/register/options/").data
        cred = auth.create(opts["options"])
        self.assertEqual(c.post("/api/auth/webauthn/register/",
                                {"state": opts["state"], "credential": cred}, format="json").status_code, 201)
        # Replay of the same state: the row is gone.
        r = c.post("/api/auth/webauthn/register/", {"state": opts["state"], "credential": cred}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "state")
        # A wrong state is the same refusal, and an expired one is swept.
        opts = c.post("/api/auth/webauthn/register/options/").data
        WebAuthnChallenge.objects.update(expires_at=WebAuthnChallenge.objects.first().expires_at - mfa_lib_delta(600))
        r = c.post("/api/auth/webauthn/register/", {"state": opts["state"], "credential": auth.create(opts["options"])}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "state")

    def test_a_login_assertion_for_another_users_challenge_is_refused(self):
        auth, _ = self.enrol(self.owner)
        other, _ = self.enrol(self.viewer)
        r = self.challenge("owen")
        # Val's key, Owen's challenge: unknown credential on this account.
        assertion = other.get(r.data["passkey"]["options"])
        bad = APIClient().post("/api/auth/token/", {
            "username": "owen", "password": PASSWORD,
            "passkey": {"state": r.data["passkey"]["state"], "credential": assertion},
        }, format="json")
        self.assertEqual(bad.status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action="mfa", detail__contains="passkey refused (unknown)").exists())
        self.assertTrue(AuditLog.objects.filter(action="login_failed", detail__contains="invalid second factor").exists())

    def test_a_wrong_origin_is_refused_at_sign_in(self):
        auth, _ = self.enrol(self.owner)
        r = self.login_with("owen", auth, origin="https://phish.example")
        self.assertEqual(r.status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action="mfa", detail__contains="passkey refused (origin)").exists())

    def test_rs256_and_eddsa_keys_enrol_and_sign_in(self):
        for alg, name in ((wa.RS256, "RS256"), (wa.EDDSA, "EdDSA")):
            auth, r = self.enrol(self.owner, FakeAuthenticator(alg), name=name)
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(r.data["algorithm"], name)
            self.assertEqual(self.login_with("owen", auth).status_code, 200)

    def test_totp_and_a_passkey_are_alternatives(self):
        secret = mfa_lib.generate_secret()
        MfaDevice.objects.create(user=self.owner, secret=secret, enabled=True)
        auth, _ = self.enrol(self.owner)
        r = self.challenge("owen")
        self.assertEqual(r.data["factors"],
                         {"totp": True, "passkey": True, "passkey_suspect": 0, "backup_codes": False})
        self.assertEqual(self.login_with("owen", auth).status_code, 200)
        code = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD,
                                                     "otp": mfa_lib.totp(secret)}, format="json")
        self.assertEqual(code.status_code, 200)

    def test_a_code_is_refused_when_only_passkeys_are_enrolled(self):
        self.enrol(self.owner)
        r = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD, "otp": "123456"},
                             format="json")
        self.assertEqual(r.status_code, 401)

    def test_enrolment_limit_and_duplicate_keys(self):
        auth, r = self.enrol(self.owner)
        self.assertEqual(r.status_code, 201)
        _, again = self.enrol(self.owner, auth)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.data["code"], "duplicate")
        with override_settings(WEBAUTHN_RP_ID=RP_ID):
            from accounts import passkeys
            with mock_max(passkeys, 2):
                _, ok = self.enrol(self.owner, name="Second")
                self.assertEqual(ok.status_code, 201)
                r = self.client_for(self.owner).post("/api/auth/webauthn/register/options/")
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.data["code"], "limit")

    @override_settings(WEBAUTHN_USER_VERIFICATION="required")
    def test_user_verification_can_be_required(self):
        auth, r = self.enrol(self.owner, FakeAuthenticator(user_verified=False))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "verification")
        auth, r = self.enrol(self.owner, FakeAuthenticator(user_verified=True))
        self.assertEqual(r.status_code, 201)
        auth.user_verified = False
        self.assertEqual(self.login_with("owen", auth).status_code, 401)

    @override_settings(WEBAUTHN_RP_ID="grc.example.com", WEBAUTHN_ORIGINS=["https://grc.example.com"])
    def test_the_relying_party_can_be_pinned(self):
        auth = FakeAuthenticator()
        auth.rp_id, auth.origin = "grc.example.com", "https://grc.example.com"
        _, r = self.enrol(self.owner, auth)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.client_for(self.owner).get("/api/auth/webauthn/").data["rp_id"], "grc.example.com")
        self.assertEqual(self.login_with("owen", auth).status_code, 200)
        # The request's own origin is no longer enough.
        self.assertEqual(self.login_with("owen", auth, origin=ORIGIN).status_code, 401)


# --------------------------------------------------------------------------- #
# Management: rename, remove, admin reset
# --------------------------------------------------------------------------- #
class ManagementTests(PasskeyTestBase):
    def test_list_rename_and_remove_with_password(self):
        auth, r = self.enrol(self.owner)
        pk = r.data["id"]
        c = self.client_for(self.owner)
        listed = c.get("/api/auth/webauthn/").data
        self.assertEqual([x["name"] for x in listed["results"]], ["Laptop"])
        self.assertEqual(c.patch(f"/api/auth/webauthn/{pk}/", {"name": "Work laptop"}, format="json").data["name"],
                         "Work laptop")
        self.assertEqual(c.delete(f"/api/auth/webauthn/{pk}/", {"password": "wrong"}, format="json").status_code, 400)
        self.assertEqual(c.delete(f"/api/auth/webauthn/{pk}/", {"password": PASSWORD}, format="json").status_code, 200)
        self.assertFalse(WebAuthnCredential.objects.filter(pk=pk).exists())
        # Nobody else's key is reachable through the same route.
        _, other = self.enrol(self.viewer)
        self.assertEqual(c.delete(f"/api/auth/webauthn/{other.data['id']}/", {"password": PASSWORD},
                                  format="json").status_code, 404)
        # And with the last factor gone, the password alone signs in again.
        r = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_admin_reset_removes_passkeys_too(self):
        self.enrol(self.owner)
        r = self.client_for(self.admin).post(f"/api/users/{self.owner.pk}/reset_mfa/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(WebAuthnCredential.objects.filter(user=self.owner).exists())
        self.assertTrue(AuditLog.objects.filter(action="mfa", detail__contains="1 passkey(s) removed").exists())


# --------------------------------------------------------------------------- #
# The clone detector fails closed
# --------------------------------------------------------------------------- #
class CloneTests(PasskeyTestBase):
    def test_a_counter_that_does_not_advance_disables_the_key_but_not_the_requirement(self):
        auth, _ = self.enrol(self.owner)
        self.assertEqual(self.login_with("owen", auth).status_code, 200)      # counter 1
        self.assertEqual(self.login_with("owen", auth).status_code, 200)      # counter 2
        # A clone signs with the counter it captured.
        r = self.login_with("owen", auth, count=2)
        self.assertEqual(r.status_code, 401)
        row = WebAuthnCredential.objects.get(user=self.owner)
        self.assertIsNotNone(row.suspect_at)
        self.assertIn("2 to 2", row.suspect_reason)
        self.assertTrue(AuditLog.objects.filter(action="mfa", detail__contains="passkey refused (clone)").exists())

        # The account still demands a second factor -- the password alone is
        # a challenge with nothing usable on offer, never a sign-in.
        r = self.challenge("owen")
        # The codes issued with the key are the way back in; the key is not.
        self.assertEqual(r.data["factors"],
                         {"totp": False, "passkey": False, "passkey_suspect": 1, "backup_codes": True})
        self.assertNotIn("passkey", r.data)
        self.assertNotIn("access", r.data)
        # The real key, even with a good counter, is refused while suspect.
        r = self.challenge("owen")
        self.assertNotIn("passkey", r.data)
        # ...and an assertion smuggled in against a stale challenge is too.
        stale = auth.get({"challenge": "whatever"}, count=10)
        r = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD,
                                                  "passkey": {"state": "x", "credential": stale}}, format="json")
        self.assertEqual(r.status_code, 401)

        # Recovery: another factor (here, the administrator) and re-enrolment.
        me = self.client_for(self.owner).get("/api/auth/webauthn/").data
        self.assertFalse(me["results"][0]["usable"])
        self.assertEqual(me["factors"]["passkey_suspect"], 1)
        self.client_for(self.admin).post(f"/api/users/{self.owner.pk}/reset_mfa/")
        self.assertEqual(APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD},
                                          format="json").status_code, 200)

    def test_a_key_that_never_counts_is_not_a_clone(self):
        auth, _ = self.enrol(self.owner, FakeAuthenticator(counts=False))
        for _ in range(3):
            self.assertEqual(self.login_with("owen", auth).status_code, 200)
        self.assertIsNone(WebAuthnCredential.objects.get(user=self.owner).suspect_at)

    def test_the_person_can_remove_a_suspect_key_with_their_password_and_re_enrol(self):
        secret = mfa_lib.generate_secret()
        MfaDevice.objects.create(user=self.owner, secret=secret, enabled=True)
        auth, r = self.enrol(self.owner)
        pk = r.data["id"]
        self.assertEqual(self.login_with("owen", auth).status_code, 200)
        self.assertEqual(self.login_with("owen", auth, count=1).status_code, 401)
        # The authenticator app still works: the factor was never dropped.
        c = APIClient()
        r = c.post("/api/auth/token/", {"username": "owen", "password": PASSWORD, "otp": mfa_lib.totp(secret)},
                   format="json")
        self.assertEqual(r.status_code, 200)
        me = self.client_for(self.owner)
        self.assertEqual(me.delete(f"/api/auth/webauthn/{pk}/", {"password": PASSWORD}, format="json").status_code, 200)
        fresh, r = self.enrol(self.owner, name="Replacement")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.login_with("owen", fresh).status_code, 200)


# --------------------------------------------------------------------------- #
# Backup codes belong to the account, so a passkey-only person has them
# --------------------------------------------------------------------------- #
class BackupCodeTests(PasskeyTestBase):
    def test_the_first_passkey_comes_with_backup_codes_that_sign_in(self):
        auth, r = self.enrol(self.owner)
        codes = r.data["backup_codes"]
        self.assertEqual(len(codes), 10)
        self.assertTrue(r.data["factors"]["backup_codes"])
        # A second key does not reissue them.
        _, again = self.enrol(self.owner, name="Second")
        self.assertIsNone(again.data["backup_codes"])
        challenge = self.challenge("owen")
        self.assertEqual((challenge.data["factors"]["totp"], challenge.data["factors"]["backup_codes"]),
                         (False, True))
        # A backup code is accepted as the `otp`, once.
        from django.core.cache import cache
        cache.clear()
        ok = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD,
                                                   "otp": codes[0]}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        cache.clear()
        again = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD,
                                                      "otp": codes[0]}, format="json")
        self.assertEqual(again.status_code, 401)
        status = self.client_for(self.owner).get("/api/auth/mfa/status/").data
        self.assertEqual((status["enabled"], status["backup_codes_remaining"]), (False, 9))

    def test_codes_regenerate_with_the_password_and_go_with_the_last_factor(self):
        auth, r = self.enrol(self.owner)
        c = self.client_for(self.owner)
        self.assertEqual(c.post("/api/auth/mfa/backup-codes/", {"password": "wrong"}, format="json").status_code, 400)
        fresh = c.post("/api/auth/mfa/backup-codes/", {"password": PASSWORD}, format="json")
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(len(fresh.data["backup_codes"]), 10)
        self.assertNotEqual(set(fresh.data["backup_codes"]), set(r.data["backup_codes"]))
        # Removing the only factor removes the codes: nothing to back up.
        c.delete(f"/api/auth/webauthn/{r.data['id']}/", {"password": PASSWORD}, format="json")
        self.assertEqual(self.owner.backup_codes_remaining, 0)
        self.assertEqual(self.client_for(self.viewer).post("/api/auth/mfa/backup-codes/",
                                                            {"password": PASSWORD}, format="json").status_code, 400)

    def test_enrolling_the_app_after_a_passkey_keeps_the_existing_codes(self):
        _, r = self.enrol(self.owner)
        c = self.client_for(self.owner)
        setup = c.post("/api/auth/mfa/setup/").data
        verify = c.post("/api/auth/mfa/verify/", {"code": mfa_lib.totp(setup["secret"])}, format="json")
        self.assertEqual(verify.status_code, 200, verify.data)
        self.assertIsNone(verify.data["backup_codes"])
        self.assertEqual(verify.data["backup_codes_remaining"], 10)
        # And the passkey's codes still sign in beside the app.
        from django.core.cache import cache
        cache.clear()
        ok = APIClient().post("/api/auth/token/", {"username": "owen", "password": PASSWORD,
                                                   "otp": r.data["backup_codes"][3]}, format="json")
        self.assertEqual(ok.status_code, 200)


# --------------------------------------------------------------------------- #
# Step-up on single sign-on accepts a passkey
# --------------------------------------------------------------------------- #
class SsoStepUpTests(PasskeyTestBase):
    def _ticket(self, client, user):
        ticket = secrets.token_urlsafe(32)
        session = client.session
        session["oidc_ticket"] = {
            "hash": hashlib.sha256(ticket.encode("ascii")).hexdigest(),
            "user": user.pk, "exp": int(time.time()) + 300, "mfa": True, "tries": 0,
        }
        session.save()
        return ticket

    def test_the_redeem_step_offers_and_accepts_a_passkey(self):
        auth, _ = self.enrol(self.viewer)
        anon = APIClient()
        ticket = self._ticket(anon, self.viewer)
        r = anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["mfa_required"])
        self.assertEqual(r.data["factors"]["passkey"], True)
        assertion = auth.get(r.data["passkey"]["options"])
        r = anon.post("/api/auth/oidc/redeem/", {
            "ticket": ticket, "passkey": {"state": r.data["passkey"]["state"], "credential": assertion},
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertTrue(AuditLog.objects.filter(action="login", detail__contains="passkey verified").exists())

    def test_a_bad_passkey_spends_a_try_and_a_clone_is_refused(self):
        auth, _ = self.enrol(self.viewer)
        anon = APIClient()
        ticket = self._ticket(anon, self.viewer)
        r = anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        bad = auth.get(r.data["passkey"]["options"], origin="https://phish.example")
        r2 = anon.post("/api/auth/oidc/redeem/", {
            "ticket": ticket, "passkey": {"state": r.data["passkey"]["state"], "credential": bad}}, format="json")
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.data["code"], "mfa_invalid")
        # The ticket survives; a fresh challenge and a good assertion finish it.
        r = anon.post("/api/auth/oidc/redeem/", {"ticket": ticket}, format="json")
        good = auth.get(r.data["passkey"]["options"])
        r3 = anon.post("/api/auth/oidc/redeem/", {
            "ticket": ticket, "passkey": {"state": r.data["passkey"]["state"], "credential": good}}, format="json")
        self.assertIn("access", r3.data)

    def test_step_up_applies_to_passkey_only_accounts(self):
        """SSO_STEP_UP=if_enrolled counts a passkey as an enrolled factor."""
        from accounts.oidc import step_up_needed
        self.assertFalse(step_up_needed(self.viewer, asserted=False))
        self.enrol(self.viewer)
        self.assertTrue(step_up_needed(self.viewer, asserted=False))
        self.assertFalse(step_up_needed(self.viewer, asserted=True))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def mfa_lib_delta(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


class mock_max:
    """Temporarily lower the passkey ceiling."""

    def __init__(self, module, n):
        self.module, self.n = module, n

    def __enter__(self):
        self.old = self.module.MAX_PASSKEYS
        self.module.MAX_PASSKEYS = self.n

    def __exit__(self, *exc):
        self.module.MAX_PASSKEYS = self.old
