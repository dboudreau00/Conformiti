"""Ed25519 detached signatures over the sealed manifest. The key lives in ``SIGNING_KEY_FILE`` or ``SIGNING_KEY``,
never in the database: a dump, a backup or a SQL injection must not yield it."""
import base64
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
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


def _read_key_file(path, where):
    """The key in an existing key file. A blank file raises: reading it as "no key" would leave every package unsigned
    without a word."""
    key = _parse_private(path.read_text(encoding="utf-8"), where)
    if key is None:
        raise ImproperlyConfigured(
            f"{where}: the file exists but is empty, so nothing can be signed. Restore it "
            "from a backup, or delete it to have a new key generated (packages sealed under "
            "the lost key then verify only against the fingerprint published for it).")
    return key


def _generate_into(path):
    """Create a key file at 0600; None when another worker got there first (the caller re-reads)."""
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written whole under a private name, then linked into place: creating the final name first lets another process
    # read an empty file, which parses as "no key" and leaves the package unsigned.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(str(tmp), str(path))     # atomic, and refuses an existing name
        except FileExistsError:
            return None
        except OSError:
            # A filesystem without hard links: fall back to exclusive create.
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return None
            with os.fdopen(fd, "wb") as fh:
                fh.write(pem)
    finally:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
    return key


def load_private_key(create=True):
    """The installation's signing key, or None when signing is off or no key location is configured.
    Cached by file mtime, so a rotation is picked up without a restart."""
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
            key = _read_key_file(path, f"SIGNING_KEY_FILE={location}")
        elif create:
            key = _generate_into(path) or _read_key_file(path, f"SIGNING_KEY_FILE={location}")
            mtime = path.stat().st_mtime_ns
        else:
            return None
    except OSError as exc:
        raise ImproperlyConfigured(f"SIGNING_KEY_FILE={location!r} is not readable/writable: {exc}")
    _cache.update(path=str(path), mtime=mtime, key=key)
    return key


# Changing this changes every workspace's derived key, so it is versioned.
_DERIVATION_INFO = b"conformiti/workspace-package-signing/v1/"


def derive_workspace_key(root_key, slug):
    """A workspace's signing key, derived from the installation key: one secret to protect and rotate, yet each
    organisation has its own identity."""
    seed = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=_DERIVATION_INFO + slug.encode("utf-8"),
    ).derive(root_key.private_bytes_raw())
    return ed25519.Ed25519PrivateKey.from_private_bytes(seed)


def active_private_key(create=True):
    """The key that signs for the current workspace; the installation key when none is active (management commands,
    the health endpoint)."""
    root = load_private_key(create=create)
    if root is None:
        return None
    from accounts import tenancy

    workspace = tenancy.current()
    return derive_workspace_key(root, workspace.slug) if workspace is not None else root


def public_raw(public_key):
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_b64(public_key):
    return base64.b64encode(public_raw(public_key)).decode("ascii")


def public_pem(public_key):
    return public_key.public_bytes(serialization.Encoding.PEM,
                                   serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def fingerprint(public_key_or_b64):
    """SHA-256 of the raw 32-byte public key, hex; the first 16 characters are the key id."""
    raw = (public_raw(public_key_or_b64) if hasattr(public_key_or_b64, "public_bytes")
           else base64.b64decode(public_key_or_b64))
    return hashlib.sha256(raw).hexdigest()


def key_id(public_key_or_b64):
    return fingerprint(public_key_or_b64)[:16]


def public_from_b64(text):
    return ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(text))


def sign_bytes(raw):
    """``(signature_b64, key_id, public_key_b64)`` under the active workspace's key, or None when unsigned."""
    key = active_private_key()
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
    """Record the key that just signed as current and retire this workspace's other current keys (a rotation made
    without the command)."""
    from django.db import IntegrityError, transaction

    from .models import SigningKey

    from accounts import tenancy

    workspace_id = tenancy.current_id()
    kid = key_id(public_key_b64)
    # Found by the whole public key. key_id is a unique label: a different key sharing it raises IntegrityError
    # rather than reuse the other key's row.
    try:
        with transaction.atomic():
            row, _ = SigningKey.objects.get_or_create(
                public_key=public_key_b64, defaults={"key_id": kid, "workspace_id": workspace_id})
    except IntegrityError:
        raise ImproperlyConfigured(
            f"Signing key id {kid} is already registered for a different public key; "
            "rotate the signing key.")
    if row.retired_at is not None or row.workspace_id != workspace_id:
        row.retired_at = None
        row.workspace_id = workspace_id
        row.save(update_fields=["retired_at", "workspace"])
    # Only this workspace's keys: each organisation has its own current key.
    (SigningKey.objects.filter(retired_at__isnull=True, workspace_id=workspace_id)
     .exclude(pk=row.pk).update(retired_at=timezone.now()))
    return row


def sign_package(package):
    """Sign ``manifest_json`` as stored; returns the key id, or "" when there is no signing key."""
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
    """'valid', 'invalid' or 'unsigned', judged against the registered public key and never the copy on the package row:
    anyone able to write the table could re-sign a doctored manifest with a key of their own."""
    from .models import SigningKey

    if not package.manifest_signature:
        return "unsigned"
    if not package.signing_public_key:
        return "invalid"
    known = SigningKey.objects.filter(public_key=package.signing_public_key).first()
    if known is None or known.key_id != package.signing_key_id:
        return "invalid"
    # Keys from before per-workspace signing carry no workspace and stay acceptable.
    if known.workspace_id is not None and package.workspace_id is not None \
            and known.workspace_id != package.workspace_id:
        return "invalid"
    ok = verify_bytes((package.manifest_json or "").encode("utf-8"),
                      package.manifest_signature, known.public_key)
    return "valid" if ok else "invalid"


def current_key_info(create=True):
    """Key details for the health endpoint and settings screen; a configuration error comes back as ``error``, not
    raised."""
    try:
        key = active_private_key(create=create)
    except ImproperlyConfigured as exc:
        return {"enabled": enabled(), "algorithm": ALGORITHM, "key_id": None, "fingerprint": None,
                "public_key": None, "error": str(exc)}
    if key is None:
        return {"enabled": enabled(), "algorithm": ALGORITHM, "key_id": None, "fingerprint": None,
                "public_key": None, "error": None}
    pub = key.public_key()
    return {"enabled": True, "algorithm": ALGORITHM, "key_id": key_id(pub),
            "fingerprint": fingerprint(pub), "public_key": public_b64(pub), "error": None}
