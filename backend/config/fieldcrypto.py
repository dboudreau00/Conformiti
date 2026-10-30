"""AES-256-GCM field encryption. ``settings.FIELD_ENCRYPTION_KEYS`` is a ring, newest first: the first key encrypts and
every key decrypts. The AAD (``table:column:row-id``) binds a ciphertext to its row, so a transplant fails."""
import base64
import hashlib
import hmac
import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.query_utils import DeferredAttribute

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "fc1$"
_NONCE_BYTES = 12
# Domain separation, so a key never yields the same bytes as elsewhere it is used (SECRET_KEY also signs JWTs).
_HKDF_SALT = b"conformiti.fieldcrypto.v1"
_HKDF_INFO = b"aes-256-gcm"

_derived_cache = {}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(entry: str) -> bytes:
    """HKDF-SHA256 a ring entry down to a 32-byte AES key."""
    cached = _derived_cache.get(entry)
    if cached is not None:
        return cached
    prk = hmac.new(_HKDF_SALT, entry.encode("utf-8"), hashlib.sha256).digest()
    okm = hmac.new(prk, _HKDF_INFO + b"\x01", hashlib.sha256).digest()
    _derived_cache[entry] = okm
    return okm


def _key_id(key: bytes) -> str:
    """A short public fingerprint of a derived key; never key material."""
    return _b64(hashlib.sha256(b"key-id" + key).digest())[:8]


def ring():
    """The key ring, newest first, read per call so ``@override_settings`` works in tests."""
    keys = getattr(settings, "FIELD_ENCRYPTION_KEYS", None) or []
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is empty. Set DJANGO_FIELD_ENCRYPTION_KEY or "
            "DJANGO_FIELD_ENCRYPTION_KEY_FILE (see .env.example)."
        )
    return [_derive(k) for k in keys]


def key_ids():
    return [_key_id(k) for k in ring()]


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def aad_for(table: str, column: str, row_id) -> bytes:
    """Single definition of the AAD: the migration path and the live field must agree byte for byte."""
    return f"{table}:{column}:{row_id}".encode("utf-8")


def encrypt(plaintext: str, aad: bytes) -> str:
    if plaintext is None:
        return plaintext
    key = ring()[0]
    nonce = os.urandom(_NONCE_BYTES)
    blob = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return f"{PREFIX}{_key_id(key)}${_b64(nonce)}${_b64(blob)}"


def decrypt(envelope: str, aad: bytes):
    """Plaintext, or None when no key in the ring can read it. None means unreadable, not empty:
    callers must not persist it over the stored ciphertext."""
    if not is_encrypted(envelope):
        return envelope
    try:
        _, kid, nonce_b64, blob_b64 = envelope.split("$", 3)
        nonce, blob = _unb64(nonce_b64), _unb64(blob_b64)
    except (ValueError, base64.binascii.Error):
        return None
    keys = ring()
    ordered = sorted(keys, key=lambda k: _key_id(k) != kid)
    for key in ordered:
        try:
            return AESGCM(key).decrypt(nonce, blob, aad).decode("utf-8")
        except (InvalidTag, ValueError):
            continue
    return None


def envelope_key_id(envelope: str):
    if not is_encrypted(envelope):
        return None
    parts = envelope.split("$", 3)
    return parts[1] if len(parts) == 4 else None


def ciphertext_length(plaintext_bytes: int) -> int:
    body = _NONCE_BYTES + plaintext_bytes + 16  # + GCM tag
    return len(PREFIX) + 8 + 1 + ((_NONCE_BYTES * 4 + 2) // 3) + 1 + ((body * 4 + 2) // 3) + 2


class _EncryptedAttribute(DeferredAttribute):
    """Decrypts on attribute access, not in ``from_db_value``: the AAD needs another column of the same row.
    ``__set__`` makes it a data descriptor; without it the raw column in ``__dict__`` wins and nothing is decrypted."""

    def __set__(self, instance, value):
        instance.__dict__[self.field.attname] = value
        unreadable = getattr(instance, "_fieldcrypto_unreadable", None)
        if unreadable:
            unreadable.pop(self.field.attname, None)

    def __get__(self, instance, cls=None):
        if instance is None:
            return self
        value = super().__get__(instance, cls)
        if not is_encrypted(value):
            return value
        plaintext = decrypt(value, self.field.aad_for_instance(instance))
        if plaintext is None:
            # Keep the ciphertext so pre_save can write it back: a mistyped key must not shred the column.
            store = instance.__dict__.setdefault("_fieldcrypto_unreadable", {})
            store[self.field.attname] = value
            instance.__dict__[self.field.attname] = ""
            return ""
        instance.__dict__[self.field.attname] = plaintext
        return plaintext


class EncryptedCharField(models.CharField):
    """A CharField stored encrypted. ``aad_from`` must be set before the INSERT (a database-assigned id cannot bind);
    ``max_length`` is the envelope width, so size it with ``ciphertext_length()``."""

    descriptor_class = _EncryptedAttribute

    def __init__(self, *args, aad_from="id", **kwargs):
        self.aad_from = aad_from
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.aad_from != "id":
            kwargs["aad_from"] = self.aad_from
        return name, path, args, kwargs

    def aad_for_instance(self, instance):
        row_id = getattr(instance, self.aad_from, None)
        if row_id is None:
            raise ValueError(
                f"{instance.__class__.__name__}.{self.attname} is encrypted and bound to "
                f"'{self.aad_from}', which is not set yet. Assign it before saving."
            )
        return aad_for(instance._meta.db_table, self.column, row_id)

    def pre_save(self, model_instance, add):
        value = getattr(model_instance, self.attname)

        # A value we could not read is written back exactly as it was found.
        unreadable = model_instance.__dict__.get("_fieldcrypto_unreadable") or {}
        if self.attname in unreadable and not value:
            return unreadable[self.attname]

        # Already an envelope (rotation assigns raw ciphertext): never wrap twice.
        if is_encrypted(value):
            return value
        if value in (None, ""):
            return value
        return encrypt(value, self.aad_for_instance(model_instance))


def encrypt_existing_rows(connection, table, column, aad_column):
    """Encrypt the plaintext rows of a column; idempotent, so a re-run after a partial failure is safe.
    Use the connection from ``schema_editor``, not the global one, or a non-default database is missed."""
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        # S608: identifiers are the migration's own constants, quoted; every value is a bound %s parameter.
        cursor.execute(  # noqa: S608
            f"SELECT {quote(aad_column)}, {quote(column)} FROM {quote(table)} "
            f"WHERE {quote(column)} IS NOT NULL AND {quote(column)} <> ''"
        )
        rows = cursor.fetchall()
        done = 0
        for row_id, value in rows:
            if is_encrypted(value):
                continue
            envelope = encrypt(value, aad_for(table, column, row_id))
            cursor.execute(  # noqa: S608 (quoted identifiers, bound values)
                f"UPDATE {quote(table)} SET {quote(column)} = %s WHERE {quote(aad_column)} = %s",
                [envelope, row_id],
            )
            done += 1
    return done


def decrypt_existing_rows(connection, table, column, aad_column):
    """The reverse migration: writes plaintext back on purpose; rows no key can read are left as they are."""
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        # S608: identifiers are the migration's own constants, quoted; every value is a bound %s parameter.
        cursor.execute(  # noqa: S608
            f"SELECT {quote(aad_column)}, {quote(column)} FROM {quote(table)} "
            f"WHERE {quote(column)} IS NOT NULL AND {quote(column)} <> ''"
        )
        rows = cursor.fetchall()
        done = 0
        for row_id, value in rows:
            if not is_encrypted(value):
                continue
            plaintext = decrypt(value, aad_for(table, column, row_id))
            if plaintext is None:
                continue
            cursor.execute(  # noqa: S608 (quoted identifiers, bound values)
                f"UPDATE {quote(table)} SET {quote(column)} = %s WHERE {quote(aad_column)} = %s",
                [plaintext, row_id],
            )
            done += 1
    return done
