"""
Detached signatures over the sealed manifest.

Until 0.7.0 a bundle proved integrity and not origin: anyone who could rewrite
it could rewrite manifest.json and every checksum consistently. The seal
entry in the audit trail and a digest published out of band were the only
binding to a moment. This module adds the signature that was deliberately
left out until there was a key-management story worth stating:

* **The key never lives in the database.** It is an Ed25519 private key in a
  file (``SIGNING_KEY_FILE``, generated at 0600 on first use -- in the
  compose stack inside the ``secrets`` volume beside the Django secret key)
  or in the environment (``SIGNING_KEY``). A database dump, a backup, or a
  SQL injection yields the evidence and every digest, but not the key.
* **The public key is published**, at ``GET /api/signing-keys/`` and on the
  package screen, so an auditor can fetch the fingerprint from the running
  installation -- or, better, be handed it out of band -- and compare it
  with the key inside the bundle.
* **The bundle verifies offline** with the standard library alone:
  ``verify.py`` carries its own Ed25519 implementation. ``openssl`` works
  too (the README says how).
* **Rotation keeps history.** ``manage.py rotate_signing_key`` writes a new
  key; every package remembers the public key that signed it, and the
  ``SigningKey`` table lists current and retired keys with their dates.

What the signature proves: that the manifest bytes were signed by whoever
held the installation's signing key when the package was sealed. What it
does not prove: that the key was never stolen. The audit trail's seal entry,
the published fingerprint and the key file's permissions are the rest of
the story, and SECURITY.md says so.
"""
import base64
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

ALGORITHM = "Ed25519"
_cache = {"path": None, "mtime": None, "key": None}


def enabled():
    return bool(getattr(settings, "SIGNING_ENABLED", True))


def _parse_private(text, where):
    text = (text or "").strip()
    if not text:
        return None
    if "BEGIN" in text:
        try:
            key = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(f"{where}: not a readable PEM private key ({exc})")
    else:
        try:
            raw = base64.b64decode(text.replace("-", "+").replace("_", "/") + "=" * (-len(text) % 4))
            key = ed25519.Ed25519PrivateKey.from_private_bytes(raw)
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(f"{where}: not a base64 32-byte Ed25519 seed ({exc})")
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ImproperlyConfigured(f"{where}: the signing key must be Ed25519")
    return key


def _generate_into(path):
    """Create a new key file at 0600, or return None if another worker got
    there first (the caller re-reads)."""
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return None
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return key


def load_private_key(create=True):
    """The installation's signing key, or None when signing is off or no key
    location is configured. Cached by file mtime, so a rotation is picked up
    without a restart."""
    if not enabled():
        return None
    explicit = getattr(settings, "SIGNING_KEY", "") or ""
    if explicit.strip():
        return _parse_private(explicit, "SIGNING_KEY")
    location = (getattr(settings, "SIGNING_KEY_FILE", "") or "").strip()
    if not location:
        return None
    path = Path(location)
    try:
        if path.exists():
            mtime = path.stat().st_mtime_ns
            if _cache["path"] == str(path) and _cache["mtime"] == mtime and _cache["key"] is not None:
                return _cache["key"]
            key = _parse_private(path.read_text(encoding="utf-8"), f"SIGNING_KEY_FILE={location}")
        elif create:
            key = _generate_into(path) or _parse_private(path.read_text(encoding="utf-8"),
                                                          f"SIGNING_KEY_FILE={location}")
            mtime = path.stat().st_mtime_ns
        else:
            return None
    except OSError as exc:
        raise ImproperlyConfigured(f"SIGNING_KEY_FILE={location!r} is not readable/writable: {exc}")
    _cache.update(path=str(path), mtime=mtime, key=key)
    return key


# --------------------------------------------------------------------------- #
# Public-key encodings
# --------------------------------------------------------------------------- #
def public_raw(public_key):
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_b64(public_key):
    return base64.b64encode(public_raw(public_key)).decode("ascii")


def public_pem(public_key):
    return public_key.public_bytes(serialization.Encoding.PEM,
                                   serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def fingerprint(public_key_or_b64):
    """SHA-256 of the raw 32-byte public key, hex. The first 16 characters
    are the key id people compare; the whole thing is what verify.py prints."""
    raw = (public_raw(public_key_or_b64) if hasattr(public_key_or_b64, "public_bytes")
           else base64.b64decode(public_key_or_b64))
    return hashlib.sha256(raw).hexdigest()


def key_id(public_key_or_b64):
    return fingerprint(public_key_or_b64)[:16]


def public_from_b64(text):
    return ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(text))


# --------------------------------------------------------------------------- #
# Signing and verifying
# --------------------------------------------------------------------------- #
def sign_bytes(raw):
    """``(signature_b64, key_id, public_key_b64)`` or None when unsigned."""
    key = load_private_key()
    if key is None:
        return None
    pub = key.public_key()
    return base64.b64encode(key.sign(raw)).decode("ascii"), key_id(pub), public_b64(pub)


def verify_bytes(raw, signature_b64, public_key_b64):
    try:
        public_from_b64(public_key_b64).verify(base64.b64decode(signature_b64), raw)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def register_key(public_key_b64):
    """Record the key that just signed as current; anything else still marked
    current is retired as of now (a rotation made without the command)."""
    from .models import SigningKey

    kid = key_id(public_key_b64)
    row, _ = SigningKey.objects.get_or_create(key_id=kid, defaults={"public_key": public_key_b64})
    if row.retired_at is not None:
        row.retired_at = None
        row.save(update_fields=["retired_at"])
    SigningKey.objects.filter(retired_at__isnull=True).exclude(key_id=kid).update(retired_at=timezone.now())
    return row


def sign_package(package):
    """Sign the sealed manifest as stored. Returns the key id, or "" when
    the installation has no signing key."""
    raw = (package.manifest_json or "").encode("utf-8")
    result = sign_bytes(raw) if raw else None
    if result is None:
        package.manifest_signature = ""
        package.signing_key_id = ""
        package.signing_public_key = ""
    else:
        package.manifest_signature, package.signing_key_id, package.signing_public_key = result
        register_key(package.signing_public_key)
    package.save(update_fields=["manifest_signature", "signing_key_id", "signing_public_key"])
    return package.signing_key_id


def signature_status(package):
    """'valid', 'invalid' or 'unsigned' for the stored manifest and signature."""
    if not package.manifest_signature:
        return "unsigned"
    ok = verify_bytes((package.manifest_json or "").encode("utf-8"),
                      package.manifest_signature, package.signing_public_key)
    return "valid" if ok else "invalid"


def current_key_info(create=True):
    """What the health endpoint and the settings screen show."""
    try:
        key = load_private_key(create=create)
    except ImproperlyConfigured as exc:
        return {"enabled": enabled(), "algorithm": ALGORITHM, "key_id": None, "fingerprint": None,
                "public_key": None, "error": str(exc)}
    if key is None:
        return {"enabled": enabled(), "algorithm": ALGORITHM, "key_id": None, "fingerprint": None,
                "public_key": None, "error": None}
    pub = key.public_key()
    return {"enabled": True, "algorithm": ALGORITHM, "key_id": key_id(pub),
            "fingerprint": fingerprint(pub), "public_key": public_b64(pub), "error": None}
