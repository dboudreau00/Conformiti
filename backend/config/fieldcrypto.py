"""
Application-level encryption for the two columns that hold secrets the
application must be able to read back.

Most secrets in Conformiti are hashed: passwords, MFA backup codes. Two cannot
be, because the server needs the original value to do its job — the TOTP shared
secret (to compute the expected code) and the Jira API token (to authenticate
outbound calls). Those are encrypted here instead, so a database dump, a stolen
backup or a read-only SQL injection does not hand over working secrets.

Design
------
* **AES-256-GCM.** Authenticated, so tampering is detected rather than silently
  decrypting to garbage. Nonces are random per write.
* **A key ring, newest first.** ``settings.FIELD_ENCRYPTION_KEYS[0]`` encrypts;
  every key can decrypt. That is what makes rotation possible without downtime:
  add a new key at the front, run ``manage.py rotate_field_keys``, then drop the
  old one. The ring is read on every call so tests can override it.
* **Associated data binds the ciphertext to its row.** The AAD is
  ``table:column:row-id``, so a ciphertext lifted from one user's row and
  written into another's fails to decrypt. It does *not* defend against an
  attacker who can write to the database — they can simply write plaintext,
  which the read path still accepts (see ``from_db_value``). It defends against
  transplanting, which is the realistic case for a leaked dump.
* **A wrong or missing key degrades to read-only, never to data loss.** An
  envelope that will not decrypt reads as empty, and ``pre_save`` writes the
  original envelope back rather than an empty string, so a key restored later
  still recovers the value.

Envelope format::

    fc1$<key-id>$<nonce-b64url>$<ciphertext-b64url>

``key-id`` is a fingerprint *of the derived key*, never key material. It lets a
row say which key wrote it, so rotation can report progress and decryption does
not have to try every key in turn.
"""
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
# Domain separation: a key must never produce the same bytes here as anywhere
# else it is used (SECRET_KEY also signs JWTs).
_HKDF_SALT = b"conformiti.fieldcrypto.v1"
_HKDF_INFO = b"aes-256-gcm"

# Deriving a key costs a few hashes; doing it per row on a 217-row page is
# wasteful. Keyed by the ring entry, which is already a secret in memory.
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
    """A short public fingerprint of a derived key. Not key material: it is a
    hash of the derived key under a different label, truncated."""
    return _b64(hashlib.sha256(b"key-id" + key).digest())[:8]


def ring():
    """The active key ring, newest first. Read at call time, not import time,
    so ``@override_settings`` works in tests."""
    keys = getattr(settings, "FIELD_ENCRYPTION_KEYS", None) or []
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is empty. Set DJANGO_FIELD_ENCRYPTION_KEY or "
            "DJANGO_FIELD_ENCRYPTION_KEY_FILE (see .env.example)."
        )
    return [_derive(k) for k in keys]


def key_ids():
    """Fingerprints of the ring, newest first — for `rotate_field_keys --status`."""
    return [_key_id(k) for k in ring()]


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def aad_for(table: str, column: str, row_id) -> bytes:
    """The associated data that binds a ciphertext to one row and column.

    Single definition on purpose: the migration path and the live field must
    agree byte for byte, and a one-character divergence would make every
    migrated row permanently unreadable.
    """
    return f"{table}:{column}:{row_id}".encode("utf-8")


def encrypt(plaintext: str, aad: bytes) -> str:
    """Encrypt under the newest key. Returns the envelope."""
    if plaintext is None:
        return plaintext
    key = ring()[0]
    nonce = os.urandom(_NONCE_BYTES)
    blob = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return f"{PREFIX}{_key_id(key)}${_b64(nonce)}${_b64(blob)}"


def decrypt(envelope: str, aad: bytes):
    """Decrypt an envelope, or return None if no key in the ring can.

    None means "unreadable", not "empty": callers must not persist it over the
    stored ciphertext.
    """
    if not is_encrypted(envelope):
        return envelope
    try:
        _, kid, nonce_b64, blob_b64 = envelope.split("$", 3)
        nonce, blob = _unb64(nonce_b64), _unb64(blob_b64)
    except (ValueError, base64.binascii.Error):
        return None
    keys = ring()
    # Try the key the row names first, then the rest — a ring that has rotated
    # holds rows written under several keys at once.
    ordered = sorted(keys, key=lambda k: _key_id(k) != kid)
    for key in ordered:
        try:
            return AESGCM(key).decrypt(nonce, blob, aad).decode("utf-8")
        except (InvalidTag, ValueError):
            continue
    return None


def envelope_key_id(envelope: str):
    """Which key wrote this row, or None if it is not an envelope."""
    if not is_encrypted(envelope):
        return None
    parts = envelope.split("$", 3)
    return parts[1] if len(parts) == 4 else None


def ciphertext_length(plaintext_bytes: int) -> int:
    """Envelope length for a plaintext of this many bytes — used to size columns."""
    body = _NONCE_BYTES + plaintext_bytes + 16  # + GCM tag
    return len(PREFIX) + 8 + 1 + ((_NONCE_BYTES * 4 + 2) // 3) + 1 + ((body * 4 + 2) // 3) + 2


# --------------------------------------------------------------------------- #
# Model field
# --------------------------------------------------------------------------- #
class _EncryptedAttribute(DeferredAttribute):
    """Decrypts on attribute access.

    It has to be here rather than in ``from_db_value``: the AAD needs another
    column from the same row, and ``from_db_value`` is handed only the value.

    ``__set__`` is what makes this a *data* descriptor. Without it Python's
    lookup rules hand back ``instance.__dict__[attname]`` — which
    ``Model.__init__`` fills with the raw column — and the decryption below
    never runs at all. ``FileField``'s descriptor is a data descriptor for the
    same reason.
    """

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
            # Keep the ciphertext so pre_save can write it back untouched. A
            # mistyped key must not shred the column.
            store = instance.__dict__.setdefault("_fieldcrypto_unreadable", {})
            store[self.field.attname] = value
            instance.__dict__[self.field.attname] = ""
            return ""
        instance.__dict__[self.field.attname] = plaintext
        return plaintext


class EncryptedCharField(models.CharField):
    """A CharField whose value is AES-256-GCM encrypted in the database.

    ``aad_from`` names the attribute that identifies the row for the associated
    data. It must be populated *before* the row is written, because ``pre_save``
    runs ahead of the INSERT — ``user_id`` on a OneToOne, or an explicitly-set
    ``id`` on a singleton row. A field whose id is only assigned by the database
    cannot be bound this way.

    ``max_length`` is the width of the stored *envelope*, not of the plaintext;
    size it with ``ciphertext_length()``.
    """

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

        # Already an envelope: a caller assigned raw ciphertext (rotation does
        # this). Never wrap twice.
        if is_encrypted(value):
            return value
        if value in (None, ""):
            return value
        return encrypt(value, self.aad_for_instance(model_instance))


# --------------------------------------------------------------------------- #
# Migration helpers
# --------------------------------------------------------------------------- #
def encrypt_existing_rows(connection, table, column, aad_column):
    """Encrypt plaintext values already in a table. Idempotent: rows that are
    already envelopes, empty or NULL are skipped, so a re-run after a partial
    failure is safe.

    Takes the connection from ``schema_editor`` rather than the global one so a
    migration on a non-default database still writes to the right place.
    """
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {quote(aad_column)}, {quote(column)} FROM {quote(table)} "
            f"WHERE {quote(column)} IS NOT NULL AND {quote(column)} <> ''"
        )
        rows = cursor.fetchall()
        done = 0
        for row_id, value in rows:
            if is_encrypted(value):
                continue
            envelope = encrypt(value, aad_for(table, column, row_id))
            cursor.execute(
                f"UPDATE {quote(table)} SET {quote(column)} = %s WHERE {quote(aad_column)} = %s",
                [envelope, row_id],
            )
            done += 1
    return done


def decrypt_existing_rows(connection, table, column, aad_column):
    """The reverse migration: write plaintext back.

    This puts readable secrets in the database on purpose — it is what
    "reverse this migration" means. Rows that cannot be decrypted are left as
    they are rather than blanked.
    """
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
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
            cursor.execute(
                f"UPDATE {quote(table)} SET {quote(column)} = %s WHERE {quote(aad_column)} = %s",
                [plaintext, row_id],
            )
            done += 1
    return done
