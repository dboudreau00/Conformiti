"""
Time-based one-time passwords (TOTP, RFC 6238) and recovery codes.

Implemented on the standard library alone (hmac/hashlib/base64/struct) so MFA
adds no dependency and works with any authenticator app — Google Authenticator,
Authy, 1Password, Microsoft Authenticator, etc. Correctness is covered by the
RFC 4226 / 6238 test vectors in tests (see tools/validate.py check 13).
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
ALGO = "sha1"  # what authenticator apps default to
_BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no ambiguous 0/o/1/i/l


def generate_secret(num_bytes=20):
    """A fresh base32 secret (no padding), as authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(num_bytes)).decode("ascii").rstrip("=")


def _b32decode(secret):
    s = secret.strip().replace(" ", "").upper()
    s += "=" * (-len(s) % 8)  # restore stripped padding
    return base64.b32decode(s)


def hotp(secret, counter, digits=DIGITS, algo=ALGO):
    """RFC 4226 HMAC-based OTP for an explicit counter."""
    mac = hmac.new(_b32decode(secret), struct.pack(">Q", counter), getattr(hashlib, algo)).digest()
    offset = mac[-1] & 0x0F
    binary = (
        (mac[offset] & 0x7F) << 24
        | (mac[offset + 1] & 0xFF) << 16
        | (mac[offset + 2] & 0xFF) << 8
        | (mac[offset + 3] & 0xFF)
    )
    return str(binary % (10 ** digits)).zfill(digits)


def totp(secret, at=None, period=PERIOD, digits=DIGITS, algo=ALGO):
    """RFC 6238 time-based OTP for the given (or current) time."""
    if at is None:
        at = time.time()
    return hotp(secret, int(at // period), digits, algo)


def verify(secret, code, at=None, period=PERIOD, digits=DIGITS, algo=ALGO, window=1):
    """Constant-time check of a submitted code, allowing +/- `window` steps of
    clock drift (so a code valid in the adjacent 30s window still passes)."""
    if at is None:
        at = time.time()
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == digits):
        return False
    counter = int(at // period)
    ok = False
    for drift in range(-window, window + 1):
        # compare_digest on every candidate (no early exit) to avoid timing leaks
        if hmac.compare_digest(hotp(secret, counter + drift, digits, algo), code):
            ok = True
    return ok


def otpauth_uri(secret, account, issuer="Conformiti"):
    """The otpauth:// URI an authenticator scans (or you paste in manually)."""
    label = quote(f"{issuer}:{account}")
    params = urlencode({
        "secret": secret, "issuer": issuer,
        "algorithm": ALGO.upper(), "digits": DIGITS, "period": PERIOD,
    })
    return f"otpauth://totp/{label}?{params}"


def generate_backup_codes(count=10, groups=2, group_len=4):
    """Single-use recovery codes like ``abcd-efgh`` (shown once at enrollment)."""
    codes = []
    for _ in range(count):
        parts = [
            "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(group_len))
            for _ in range(groups)
        ]
        codes.append("-".join(parts))
    return codes


def normalize_backup_code(code):
    return (code or "").strip().lower().replace(" ", "")
