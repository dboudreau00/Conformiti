"""
WebAuthn (passkeys and security keys) as a second factor -- the protocol.

This module is the relying-party side of WebAuthn Level 2, reduced to what a
second factor needs: build the options the browser is given, and verify what
it hands back. It knows nothing about Django; ``accounts/passkeys.py`` is the
glue that stores credentials and challenges. Cryptography comes from the
``cryptography`` package the project already depends on; the CBOR and COSE
parsing is here in full because both are small, and a reader should be able
to check every byte the server trusts without following an import.

What is deliberately NOT here:

* **Attestation is not verified.** The browser is asked for ``"none"`` and
  whatever statement arrives is ignored. Attestation proves which make of
  authenticator created a key; a second factor needs only that the same key
  signs next time, and verifying attestation chains is a large surface for
  no gain to this product.
* **Discoverable (usernameless) login.** A passkey is always presented
  after the password, so the server always knows whose credentials to allow.

The counter rule that the roadmap deferred this feature over lives in
``counter_regressed`` and in ``passkeys.finish_login``: a signature counter
that fails to increase is a sign the credential was cloned, and the answer is
to refuse the sign-in and mark the credential, never to drop the account to
password-only.
"""
import base64
import hashlib
import hmac
import json
import struct
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

# COSE algorithm identifiers (RFC 9053) this relying party accepts, in the
# order they are offered to the browser. ES256 is what every authenticator
# supports; RS256 is Windows Hello; EdDSA is newer keys.
ES256, RS256, EDDSA = -7, -257, -8
ALGORITHMS = (ES256, RS256, EDDSA)
ALGORITHM_NAMES = {ES256: "ES256", RS256: "RS256", EDDSA: "EdDSA"}

# Hard ceilings on what is parsed. A browser never sends anything near these.
MAX_CLIENT_DATA = 64 * 1024
MAX_ATTESTATION = 64 * 1024
MAX_AUTH_DATA = 64 * 1024
MAX_CREDENTIAL_ID = 1023
MAX_CBOR_DEPTH = 16

FLAG_UP = 0x01   # user present
FLAG_UV = 0x04   # user verified (PIN, biometric)
FLAG_BE = 0x08   # backup eligible (synced passkey)
FLAG_BS = 0x10   # currently backed up
FLAG_AT = 0x40   # attested credential data present
FLAG_ED = 0x80   # extensions present


class WebAuthnError(Exception):
    """A response the relying party refuses. ``code`` is short and stable
    (for the audit trail); ``message`` is for a person."""

    def __init__(self, code, message=None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# --------------------------------------------------------------------------- #
# base64url
# --------------------------------------------------------------------------- #
def b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text, limit=None, what="value"):
    if not isinstance(text, str):
        raise WebAuthnError("format", f"{what} must be a base64url string")
    if limit is not None and len(text) > limit * 4 // 3 + 4:
        raise WebAuthnError("format", f"{what} is too large")
    stripped = text.strip()
    try:
        return base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4))
    except (ValueError, TypeError):
        raise WebAuthnError("format", f"{what} is not valid base64url")


# --------------------------------------------------------------------------- #
# CBOR (RFC 8949), the definite-length subset CTAP2 authenticators emit
# --------------------------------------------------------------------------- #
def _cbor_head(data, offset):
    if offset >= len(data):
        raise WebAuthnError("cbor", "truncated")
    initial = data[offset]
    major, info = initial >> 5, initial & 0x1F
    offset += 1
    if info < 24:
        return major, info, offset
    widths = {24: 1, 25: 2, 26: 4, 27: 8}
    if info not in widths:
        # 28-30 are reserved; 31 is an indefinite length, which no
        # authenticator produces and which would make sizes unbounded.
        raise WebAuthnError("cbor", "unsupported length encoding")
    width = widths[info]
    if offset + width > len(data):
        raise WebAuthnError("cbor", "truncated")
    value = int.from_bytes(data[offset:offset + width], "big")
    return major, value, offset + width


def cbor_decode(data, offset=0, depth=0):
    """Decode one item at ``offset``. Returns ``(value, next_offset)``."""
    if depth > MAX_CBOR_DEPTH:
        raise WebAuthnError("cbor", "nested too deeply")
    major, arg, offset = _cbor_head(data, offset)
    if major == 0:
        return arg, offset
    if major == 1:
        return -1 - arg, offset
    if major in (2, 3):
        if offset + arg > len(data):
            raise WebAuthnError("cbor", "truncated string")
        chunk = bytes(data[offset:offset + arg])
        if major == 3:
            try:
                chunk = chunk.decode("utf-8")
            except UnicodeDecodeError:
                raise WebAuthnError("cbor", "invalid text")
        return chunk, offset + arg
    if major == 4:
        if arg > len(data):
            raise WebAuthnError("cbor", "array length exceeds input")
        items = []
        for _ in range(arg):
            item, offset = cbor_decode(data, offset, depth + 1)
            items.append(item)
        return items, offset
    if major == 5:
        if arg > len(data):
            raise WebAuthnError("cbor", "map length exceeds input")
        out = {}
        for _ in range(arg):
            key, offset = cbor_decode(data, offset, depth + 1)
            if not isinstance(key, (int, str)):
                raise WebAuthnError("cbor", "map key must be an integer or text")
            if key in out:
                raise WebAuthnError("cbor", "duplicate map key")
            out[key], offset = cbor_decode(data, offset, depth + 1)
        return out, offset
    if major == 7:
        if arg == 20:
            return False, offset
        if arg == 21:
            return True, offset
        if arg == 22:
            return None, offset
        raise WebAuthnError("cbor", "unsupported simple value")
    # major 6 (tags) never appears in WebAuthn structures.
    raise WebAuthnError("cbor", "unsupported major type")


def cbor_loads(data):
    """Decode exactly one item that fills ``data``."""
    value, end = cbor_decode(data)
    if end != len(data):
        raise WebAuthnError("cbor", "trailing bytes")
    return value


def _cbor_len(major, n):
    if n < 24:
        return bytes([(major << 5) | n])
    for info, width in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * width):
            return bytes([(major << 5) | info]) + n.to_bytes(width, "big")
    raise ValueError("value too large for CBOR")


def cbor_dumps(value):
    """Canonical (definite-length) encoder for the same subset. Used by the
    test-suite's fake authenticator and kept beside the decoder so the two
    are reviewed together."""
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        return _cbor_len(0, value) if value >= 0 else _cbor_len(1, -1 - value)
    if isinstance(value, bytes):
        return _cbor_len(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _cbor_len(3, len(raw)) + raw
    if isinstance(value, (list, tuple)):
        return _cbor_len(4, len(value)) + b"".join(cbor_dumps(v) for v in value)
    if isinstance(value, dict):
        # Canonical CBOR orders keys by their encoded form.
        items = sorted(((cbor_dumps(k), cbor_dumps(v)) for k, v in value.items()),
                       key=lambda kv: (len(kv[0]), kv[0]))
        return _cbor_len(5, len(value)) + b"".join(k + v for k, v in items)
    raise TypeError(f"cannot encode {type(value).__name__}")


# --------------------------------------------------------------------------- #
# COSE keys (RFC 9052/9053) <-> cryptography public keys
# --------------------------------------------------------------------------- #
def cose_to_public_key(cose):
    """Return ``(public_key, algorithm)`` for a COSE_Key map, or raise."""
    if not isinstance(cose, dict):
        raise WebAuthnError("key", "credential public key is not a COSE map")
    kty, alg = cose.get(1), cose.get(3)
    if alg not in ALGORITHMS:
        raise WebAuthnError("key", f"unsupported algorithm {alg}")
    try:
        if kty == 2 and alg == ES256:
            if cose.get(-1) != 1:
                raise WebAuthnError("key", "ES256 requires the P-256 curve")
            x, y = cose.get(-2), cose.get(-3)
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
                raise WebAuthnError("key", "malformed EC2 coordinates")
            numbers = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1())
            return numbers.public_key(), ES256
        if kty == 3 and alg == RS256:
            n, e = cose.get(-1), cose.get(-2)
            if not (isinstance(n, bytes) and isinstance(e, bytes) and 256 <= len(n) <= 1024):
                raise WebAuthnError("key", "malformed RSA key")
            numbers = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big"))
            return numbers.public_key(), RS256
        if kty == 1 and alg == EDDSA:
            if cose.get(-1) != 6:
                raise WebAuthnError("key", "EdDSA requires Ed25519")
            x = cose.get(-2)
            if not (isinstance(x, bytes) and len(x) == 32):
                raise WebAuthnError("key", "malformed Ed25519 key")
            return ed25519.Ed25519PublicKey.from_public_bytes(x), EDDSA
    except ValueError as exc:
        raise WebAuthnError("key", f"invalid public key: {exc}")
    raise WebAuthnError("key", "key type does not match its algorithm")


def public_key_to_der(key):
    return key.public_bytes(serialization.Encoding.DER,
                            serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_from_der(der):
    try:
        return serialization.load_der_public_key(bytes(der))
    except (ValueError, TypeError) as exc:
        raise WebAuthnError("key", f"stored key unreadable: {exc}")


def verify_signature(key, algorithm, data, signature):
    """True when ``signature`` over ``data`` verifies under ``key``."""
    try:
        if algorithm == ES256:
            if not isinstance(key, ec.EllipticCurvePublicKey):
                return False
            key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
        elif algorithm == RS256:
            if not isinstance(key, rsa.RSAPublicKey):
                return False
            key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        elif algorithm == EDDSA:
            if not isinstance(key, ed25519.Ed25519PublicKey):
                return False
            key.verify(signature, data)
        else:
            return False
    except InvalidSignature:
        return False
    except (ValueError, TypeError):
        return False
    return True


# --------------------------------------------------------------------------- #
# Authenticator data and client data
# --------------------------------------------------------------------------- #
class AuthData:
    __slots__ = ("rp_id_hash", "flags", "sign_count", "aaguid", "credential_id", "public_key_cose")

    def __init__(self, rp_id_hash, flags, sign_count, aaguid=None, credential_id=None, public_key_cose=None):
        self.rp_id_hash = rp_id_hash
        self.flags = flags
        self.sign_count = sign_count
        self.aaguid = aaguid
        self.credential_id = credential_id
        self.public_key_cose = public_key_cose

    @property
    def user_present(self):
        return bool(self.flags & FLAG_UP)

    @property
    def user_verified(self):
        return bool(self.flags & FLAG_UV)

    @property
    def backup_eligible(self):
        return bool(self.flags & FLAG_BE)

    @property
    def backup_state(self):
        return bool(self.flags & FLAG_BS)


def parse_auth_data(raw):
    if len(raw) > MAX_AUTH_DATA:
        raise WebAuthnError("format", "authenticator data too large")
    if len(raw) < 37:
        raise WebAuthnError("format", "authenticator data too short")
    rp_id_hash = bytes(raw[:32])
    flags = raw[32]
    sign_count = struct.unpack(">I", raw[33:37])[0]
    offset = 37
    aaguid = credential_id = cose = None
    if flags & FLAG_AT:
        if len(raw) < 55:
            raise WebAuthnError("format", "attested credential data truncated")
        aaguid = str(uuid.UUID(bytes=bytes(raw[37:53])))
        length = struct.unpack(">H", raw[53:55])[0]
        if length == 0 or length > MAX_CREDENTIAL_ID:
            raise WebAuthnError("format", "credential id has an invalid length")
        if 55 + length > len(raw):
            raise WebAuthnError("format", "credential id truncated")
        credential_id = bytes(raw[55:55 + length])
        offset = 55 + length
        cose, offset = cbor_decode(raw, offset)
    if flags & FLAG_ED:
        _, offset = cbor_decode(raw, offset)
    if offset != len(raw):
        raise WebAuthnError("format", "authenticator data has trailing bytes")
    return AuthData(rp_id_hash, flags, sign_count, aaguid, credential_id, cose)


def _normalise_origin(origin):
    return str(origin or "").strip().rstrip("/").lower()


def parse_client_data(raw, expected_type, expected_challenge, origins):
    """Check the collected client data: ceremony type, our challenge, an
    origin we serve. Returns the parsed object."""
    if len(raw) > MAX_CLIENT_DATA:
        raise WebAuthnError("format", "client data too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise WebAuthnError("format", "client data is not JSON")
    if not isinstance(data, dict):
        raise WebAuthnError("format", "client data is not an object")
    if data.get("type") != expected_type:
        raise WebAuthnError("type", f"expected a {expected_type} ceremony")
    presented = str(data.get("challenge") or "")
    if not hmac.compare_digest(presented.encode("utf-8"), str(expected_challenge).encode("utf-8")):
        raise WebAuthnError("challenge", "challenge does not match")
    allowed = {_normalise_origin(o) for o in origins if o}
    if _normalise_origin(data.get("origin")) not in allowed:
        raise WebAuthnError("origin", f"origin {data.get('origin')!r} is not this site")
    if data.get("crossOrigin"):
        raise WebAuthnError("origin", "cross-origin ceremonies are refused")
    return data


def rp_id_hash(rp_id):
    return hashlib.sha256(str(rp_id).encode("utf-8")).digest()


# --------------------------------------------------------------------------- #
# Options the browser is given
# --------------------------------------------------------------------------- #
def user_handle(user_pk):
    """An opaque, stable, non-identifying ``user.id`` for the authenticator
    (the spec forbids PII here). Only informative in this design: a passkey is
    always looked up through ``allowCredentials`` after the password."""
    return hashlib.sha256(f"conformiti:webauthn:user:{user_pk}".encode("ascii")).digest()


def registration_options(*, rp_id, rp_name, challenge, user_pk, username, display_name,
                         exclude, user_verification="preferred"):
    return {
        "rp": {"id": rp_id, "name": rp_name},
        "user": {
            "id": b64url_encode(user_handle(user_pk)),
            "name": username,
            "displayName": display_name or username,
        },
        "challenge": challenge,
        "pubKeyCredParams": [{"type": "public-key", "alg": alg} for alg in ALGORITHMS],
        "timeout": 120000,
        "attestation": "none",
        "excludeCredentials": [
            {"type": "public-key", "id": cid, **({"transports": list(t)} if t else {})}
            for cid, t in exclude
        ],
        "authenticatorSelection": {
            "residentKey": "preferred",
            "userVerification": user_verification,
        },
    }


def authentication_options(*, rp_id, challenge, allow, user_verification="preferred"):
    return {
        "rpId": rp_id,
        "challenge": challenge,
        "timeout": 120000,
        "userVerification": user_verification,
        "allowCredentials": [
            {"type": "public-key", "id": cid, **({"transports": list(t)} if t else {})}
            for cid, t in allow
        ],
    }


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
class Registered:
    __slots__ = ("credential_id", "public_key_der", "algorithm", "sign_count", "aaguid",
                 "backup_eligible", "backup_state", "transports", "user_verified")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _response_of(credential):
    if not isinstance(credential, dict):
        raise WebAuthnError("format", "credential must be an object")
    if credential.get("type") not in (None, "public-key"):
        raise WebAuthnError("format", "credential type must be public-key")
    response = credential.get("response")
    if not isinstance(response, dict):
        raise WebAuthnError("format", "credential response missing")
    return response


def verify_registration(credential, *, challenge, rp_id, origins, require_user_verification=False):
    """Check a ``navigator.credentials.create()`` result and return what to
    store. Attestation is not examined (see the module docstring)."""
    response = _response_of(credential)
    client_raw = b64url_decode(response.get("clientDataJSON"), MAX_CLIENT_DATA, "clientDataJSON")
    parse_client_data(client_raw, "webauthn.create", challenge, origins)
    att_raw = b64url_decode(response.get("attestationObject"), MAX_ATTESTATION, "attestationObject")
    attestation = cbor_loads(att_raw)
    if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
        raise WebAuthnError("format", "attestation object malformed")
    if not isinstance(attestation.get("fmt"), str):
        raise WebAuthnError("format", "attestation format missing")
    auth = parse_auth_data(attestation["authData"])
    if not hmac.compare_digest(auth.rp_id_hash, rp_id_hash(rp_id)):
        raise WebAuthnError("rp_id", "credential was created for another site")
    if not auth.user_present:
        raise WebAuthnError("presence", "user presence was not confirmed")
    if require_user_verification and not auth.user_verified:
        raise WebAuthnError("verification", "user verification is required on this server")
    if auth.credential_id is None or auth.public_key_cose is None:
        raise WebAuthnError("format", "no credential in the attestation")
    raw_id = b64url_decode(str(credential.get("rawId") or credential.get("id") or ""),
                           MAX_CREDENTIAL_ID, "rawId")
    if not hmac.compare_digest(raw_id, auth.credential_id):
        raise WebAuthnError("format", "credential id does not match the attested one")
    key, algorithm = cose_to_public_key(auth.public_key_cose)
    transports = response.get("transports") or []
    if not isinstance(transports, list):
        transports = []
    transports = [str(t)[:20] for t in transports if isinstance(t, str)][:8]
    return Registered(
        credential_id=b64url_encode(auth.credential_id),
        public_key_der=public_key_to_der(key),
        algorithm=algorithm,
        sign_count=auth.sign_count,
        aaguid=auth.aaguid or "",
        backup_eligible=auth.backup_eligible,
        backup_state=auth.backup_state,
        transports=transports,
        user_verified=auth.user_verified,
    )


def verify_authentication(credential, *, challenge, rp_id, origins, public_key_der, algorithm,
                          require_user_verification=False):
    """Check a ``navigator.credentials.get()`` result against a stored key.
    Returns the authenticator data (the caller applies the counter rule)."""
    response = _response_of(credential)
    client_raw = b64url_decode(response.get("clientDataJSON"), MAX_CLIENT_DATA, "clientDataJSON")
    parse_client_data(client_raw, "webauthn.get", challenge, origins)
    auth_raw = b64url_decode(response.get("authenticatorData"), MAX_AUTH_DATA, "authenticatorData")
    auth = parse_auth_data(auth_raw)
    if not hmac.compare_digest(auth.rp_id_hash, rp_id_hash(rp_id)):
        raise WebAuthnError("rp_id", "assertion was made for another site")
    if not auth.user_present:
        raise WebAuthnError("presence", "user presence was not confirmed")
    if require_user_verification and not auth.user_verified:
        raise WebAuthnError("verification", "user verification is required on this server")
    signature = b64url_decode(response.get("signature"), 4096, "signature")
    signed = auth_raw + hashlib.sha256(client_raw).digest()
    key = public_key_from_der(public_key_der)
    if not verify_signature(key, algorithm, signed, signature):
        raise WebAuthnError("signature", "signature does not verify")
    return auth


def counter_regressed(stored, presented):
    """The clone check. An authenticator that keeps a counter increments it on
    every signature; a value that fails to increase means a second copy of the
    private key has been signing. Authenticators that do not count report 0
    both times, which is not a regression."""
    if stored == 0 and presented == 0:
        return False
    return presented <= stored
