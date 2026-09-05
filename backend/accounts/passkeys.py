"""
Passkeys: the Django side of WebAuthn.

``accounts/webauthn.py`` is the protocol; this module keeps the credentials
and challenges, resolves the relying-party id and origins for a request, and
applies the one policy that matters -- what happens when a signature counter
goes backwards.

Every ceremony is two calls: ``begin_*`` stores a challenge and returns the
options for the browser plus an opaque ``state``; ``finish_*`` looks the
challenge up by that state, verifies the browser's answer, and records the
outcome. A challenge is single-use and lives five minutes.
"""
import hashlib
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import webauthn
from .models import WebAuthnChallenge, WebAuthnCredential

CHALLENGE_TTL = 300
MAX_PASSKEYS = 10


class PasskeyRefused(Exception):
    """A passkey ceremony the server will not accept. ``code`` is stable for
    the audit trail; the message is for the person."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# Relying party
# --------------------------------------------------------------------------- #
def rp_id(request):
    """The relying-party id: WEBAUTHN_RP_ID, or the request's host without a
    port. A credential is bound to this for life, so a deployment that moves
    hostnames pins the old one here."""
    configured = getattr(settings, "WEBAUTHN_RP_ID", "") or ""
    if configured:
        return configured
    host = request.get_host() if request is not None else "localhost"
    return host.split(":")[0].lower()


def origins(request):
    """Origins whose ceremonies are accepted: WEBAUTHN_ORIGINS, or the origin
    the request arrived on (the SPA and the API share one origin)."""
    configured = getattr(settings, "WEBAUTHN_ORIGINS", None) or []
    if configured:
        return list(configured)
    if request is None:
        return []
    scheme = "https" if request.is_secure() else "http"
    return [f"{scheme}://{request.get_host()}".lower()]


def user_verification():
    return getattr(settings, "WEBAUTHN_USER_VERIFICATION", "preferred") or "preferred"


def rp_name():
    return getattr(settings, "WEBAUTHN_RP_NAME", "Conformiti") or "Conformiti"


# --------------------------------------------------------------------------- #
# Challenges
# --------------------------------------------------------------------------- #
def _hash(state):
    return hashlib.sha256(str(state or "")[:256].encode("utf-8")).hexdigest()


def _new_challenge(user, purpose):
    WebAuthnChallenge.objects.filter(expires_at__lt=timezone.now()).delete()
    state = secrets.token_urlsafe(32)
    challenge = webauthn.b64url_encode(secrets.token_bytes(32))
    WebAuthnChallenge.objects.create(
        token_hash=_hash(state), challenge=challenge, user=user, purpose=purpose,
        expires_at=timezone.now() + timezone.timedelta(seconds=CHALLENGE_TTL),
    )
    return state, challenge


def _consume_challenge(user, purpose, state):
    """Fetch-and-delete: a challenge answers exactly once, even under two
    concurrent submissions."""
    with transaction.atomic():
        row = (WebAuthnChallenge.objects.select_for_update()
               .filter(token_hash=_hash(state), user=user, purpose=purpose).first())
        if row is None:
            raise PasskeyRefused("state", "That passkey request expired or was already used. Try again.")
        challenge, expired = row.challenge, row.expires_at < timezone.now()
        row.delete()
    if expired:
        raise PasskeyRefused("state", "That passkey request expired. Try again.")
    return challenge


# --------------------------------------------------------------------------- #
# Enrolment
# --------------------------------------------------------------------------- #
def _credential_refs(user, usable_only=False):
    rows = user.usable_passkeys if usable_only else user.passkeys.all()
    return [(c.credential_id, c.transports or []) for c in rows]


def begin_registration(user, request):
    if user.passkeys.count() >= MAX_PASSKEYS:
        raise PasskeyRefused("limit", f"You already have {MAX_PASSKEYS} passkeys. Remove one first.")
    state, challenge = _new_challenge(user, WebAuthnChallenge.Purpose.REGISTER)
    options = webauthn.registration_options(
        rp_id=rp_id(request), rp_name=rp_name(), challenge=challenge,
        user_pk=user.pk, username=user.get_username(),
        display_name=user.get_full_name() or user.get_username(),
        exclude=_credential_refs(user), user_verification=user_verification(),
    )
    return {"state": state, "options": options}


def finish_registration(user, request, state, name, credential):
    challenge = _consume_challenge(user, WebAuthnChallenge.Purpose.REGISTER, state)
    try:
        registered = webauthn.verify_registration(
            credential, challenge=challenge, rp_id=rp_id(request), origins=origins(request),
            require_user_verification=user_verification() == "required",
        )
    except webauthn.WebAuthnError as exc:
        raise PasskeyRefused(exc.code, f"The passkey could not be verified ({exc.message}).")
    if WebAuthnCredential.objects.filter(credential_id=registered.credential_id).exists():
        raise PasskeyRefused("duplicate", "That passkey is already enrolled.")
    if user.passkeys.count() >= MAX_PASSKEYS:
        raise PasskeyRefused("limit", f"You already have {MAX_PASSKEYS} passkeys. Remove one first.")
    label = (name or "").strip()[:80] or _default_name(registered, user)
    return WebAuthnCredential.objects.create(
        user=user, name=label, credential_id=registered.credential_id,
        public_key=registered.public_key_der, algorithm=registered.algorithm,
        sign_count=registered.sign_count, aaguid=registered.aaguid,
        transports=registered.transports, backup_eligible=registered.backup_eligible,
        backup_state=registered.backup_state, user_verified=registered.user_verified,
    )


def _default_name(registered, user):
    kind = "Passkey" if registered.backup_eligible or "internal" in registered.transports else "Security key"
    return f"{kind} {user.passkeys.count() + 1}"


# --------------------------------------------------------------------------- #
# Sign-in
# --------------------------------------------------------------------------- #
def begin_login(user, request):
    """Options for the second step of a login: only this user's usable keys
    are allowed, so a suspect credential is never even offered."""
    allow = _credential_refs(user, usable_only=True)
    if not allow:
        return None
    state, challenge = _new_challenge(user, WebAuthnChallenge.Purpose.LOGIN)
    options = webauthn.authentication_options(
        rp_id=rp_id(request), challenge=challenge, allow=allow,
        user_verification=user_verification(),
    )
    return {"state": state, "options": options}


def finish_login(user, request, payload):
    """Verify an assertion for ``user``. Returns the credential used.

    The counter rule is applied here and it fails CLOSED: a counter that did
    not increase marks the credential suspect and refuses this sign-in; the
    account keeps requiring a second factor (the person's other passkey, their
    authenticator app or a backup code -- or an administrator's reset).
    """
    if not isinstance(payload, dict):
        raise PasskeyRefused("format", "Malformed passkey response.")
    state = payload.get("state")
    credential = payload.get("credential")
    challenge = _consume_challenge(user, WebAuthnChallenge.Purpose.LOGIN, state)
    if not isinstance(credential, dict):
        raise PasskeyRefused("format", "Malformed passkey response.")
    presented_id = str(credential.get("rawId") or credential.get("id") or "")[:1400]
    row = WebAuthnCredential.objects.filter(user=user, credential_id=presented_id).first()
    if row is None:
        raise PasskeyRefused("unknown", "That passkey is not enrolled on this account.")
    if not row.is_usable:
        raise PasskeyRefused("suspect", "That passkey was flagged as possibly cloned and is disabled. "
                                        "Use another factor, then remove and re-enrol it.")
    try:
        auth = webauthn.verify_authentication(
            credential, challenge=challenge, rp_id=rp_id(request), origins=origins(request),
            public_key_der=bytes(row.public_key), algorithm=row.algorithm,
            require_user_verification=user_verification() == "required",
        )
    except webauthn.WebAuthnError as exc:
        raise PasskeyRefused(exc.code, f"The passkey could not be verified ({exc.message}).")
    now = timezone.now()
    if webauthn.counter_regressed(row.sign_count, auth.sign_count):
        row.suspect_at = now
        row.suspect_reason = (f"signature counter went from {row.sign_count} to {auth.sign_count}; "
                              "a cloned authenticator may hold this key")[:200]
        row.save(update_fields=["suspect_at", "suspect_reason"])
        raise PasskeyRefused("clone", "This passkey's signature counter went backwards, which means a "
                                      "copy of it may exist. It has been disabled; sign in with another "
                                      "factor, then remove and re-enrol it.")
    row.sign_count = auth.sign_count
    row.last_used_at = now
    row.backup_state = auth.backup_state
    row.save(update_fields=["sign_count", "last_used_at", "backup_state"])
    return row


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def factors(user):
    """What the login screen may offer after the password."""
    usable = user.usable_passkeys.count()
    total = user.passkeys.count()
    return {
        "totp": user.totp_enabled,
        "passkey": usable > 0,
        "passkey_suspect": total - usable,
    }


def serialize(row):
    return {
        "id": row.pk,
        "name": row.name,
        "algorithm": webauthn.ALGORITHM_NAMES.get(row.algorithm, str(row.algorithm)),
        "transports": row.transports or [],
        "backup_eligible": row.backup_eligible,
        "backup_state": row.backup_state,
        "user_verified": row.user_verified,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "suspect_at": row.suspect_at,
        "suspect_reason": row.suspect_reason,
        "usable": row.is_usable,
    }
