#!/usr/bin/env python3
"""
Verify a Conformiti evidence package. Shipped inside every bundle as verify.py.

    python3 verify.py .

Read-only and standard-library only. It opens files, hashes them and prints a
verdict; it extracts nothing, writes nothing and contacts nothing. Any path in
SHA256SUMS or in the manifest that is absolute or contains a ".." segment is
refused before it is opened.

What a pass means: the files beside this script are the files that were sealed.
When the bundle carries manifest.sig and signing-key.pub, it also means the
manifest was signed by the holder of that key: compare the key fingerprint
printed below with the one the organisation published (their installation
shows it under Settings > About and at /api/signing-keys/). Without a
signature, compare the manifest digest with the one they gave you separately.

The Ed25519 check is implemented here in plain Python (RFC 8032) so nothing
needs installing; it is slow by library standards and fine for one signature.
openssl agrees with it:
    base64 -d manifest.sig > manifest.sig.bin
    openssl pkeyutl -verify -pubin -inkey signing-key.pub -rawin -in manifest.json -sigfile manifest.sig.bin

Exit codes: 0 everything matches, 1 a mismatch, 2 the bundle is unusable.
"""
import base64
import hashlib
import json
import os
import sys

CHUNK = 64 * 1024

# --------------------------------------------------------------------------- #
# Ed25519 (RFC 8032), verification only
# --------------------------------------------------------------------------- #
_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_D * y * y + 1) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("not on the curve")
    if x % 2 != 0:
        x = _P - x
    return x


_BY = 4 * _inv(5) % _P
_BX = _xrecover(_BY)
_B = (_BX, _BY, 1, _BX * _BY % _P)


def _add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    d = z1 * 2 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _decode(raw):
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        raise ValueError("bad point")
    x = _xrecover(y)
    if x & 1 != sign:
        x = _P - x
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _P != 0:
        raise ValueError("bad point")
    return x, y, 1, x * y % _P


def _encode(p):
    x, y, z, _ = p
    zi = _inv(z)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def ed25519_verify(public_key, message, signature):
    """True when ``signature`` (64 bytes) is valid for ``message`` under the
    raw 32-byte ``public_key``."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        a = _decode(public_key)
        r = _decode(signature[:32])
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % _Q
    return _encode(_mul(s, _B)) == _encode(_add(r, _mul(k, a)))


# Ed25519 SubjectPublicKeyInfo: a fixed 12-byte DER prefix, then the key.
_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def read_public_key(text):
    """The raw key from a PEM SubjectPublicKeyInfo or a bare base64 key."""
    body = "".join(line.strip() for line in text.splitlines() if not line.startswith("-----"))
    der = base64.b64decode(body)
    if der.startswith(_SPKI_PREFIX) and len(der) == len(_SPKI_PREFIX) + 32:
        return der[len(_SPKI_PREFIX):]
    if len(der) == 32:
        return der
    raise ValueError("signing-key.pub is not an Ed25519 public key")


def fingerprint(public_key):
    return hashlib.sha256(public_key).hexdigest()


# --------------------------------------------------------------------------- #
# The bundle
# --------------------------------------------------------------------------- #
def unsafe(path):
    """Reject anything that could escape the bundle directory."""
    if not path or path.startswith(("/", "\\")):
        return True
    if len(path) > 1 and path[1] == ":":
        return True
    parts = path.replace("\\", "/").split("/")
    return any(p in ("..", "") for p in parts)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_signature(root, problems):
    """Returns (status, fingerprint): 'valid', 'invalid', 'unsigned' or 'unusable'."""
    sig_path = os.path.join(root, "manifest.sig")
    key_path = os.path.join(root, "signing-key.pub")
    if not os.path.isfile(sig_path):
        return "unsigned", None
    if not os.path.isfile(key_path):
        problems.append("manifest.sig is present but signing-key.pub is missing")
        return "unusable", None
    try:
        with open(sig_path, encoding="utf-8") as fh:
            signature = base64.b64decode(fh.read().strip())
        with open(key_path, encoding="utf-8") as fh:
            public_key = read_public_key(fh.read())
        with open(os.path.join(root, "manifest.json"), "rb") as fh:
            manifest = fh.read()
    except (OSError, ValueError) as exc:
        problems.append(f"signature material unreadable: {exc}")
        return "unusable", None
    if ed25519_verify(public_key, manifest, signature):
        return "valid", fingerprint(public_key)
    problems.append("SIGNATURE DOES NOT VERIFY: manifest.json was not signed by the key in signing-key.pub, "
                    "or was altered after signing")
    return "invalid", fingerprint(public_key)


# Written after SHA256SUMS, so they cannot appear inside it.
NOT_IN_SUMS = ("SHA256SUMS", "SHA256SUMS.sig", "sums-key.pub")


def check_sums_signature(root, problems):
    """The signature over SHA256SUMS, which is what covers the rest of the
    bundle. manifest.sig is made at seal and covers manifest.json alone; the
    conclusions the auditor recorded afterwards live in controls.csv and
    samples.csv, and are inside this one.

    Returns 'valid', 'invalid', 'unsigned' or 'unusable'.
    """
    sig_path = os.path.join(root, "SHA256SUMS.sig")
    key_path = os.path.join(root, "sums-key.pub")
    if not os.path.isfile(sig_path):
        return "unsigned", None
    if not os.path.isfile(key_path):
        problems.append("SHA256SUMS.sig is present but sums-key.pub is missing")
        return "unusable", None
    try:
        with open(sig_path, encoding="utf-8") as fh:
            signature = base64.b64decode(fh.read().strip())
        with open(key_path, encoding="utf-8") as fh:
            public_key = read_public_key(fh.read())
        with open(os.path.join(root, "SHA256SUMS"), "rb") as fh:
            sums = fh.read()
    except (OSError, ValueError) as exc:
        problems.append(f"SHA256SUMS signature material unreadable: {exc}")
        return "unusable", None
    if ed25519_verify(public_key, sums, signature):
        return "valid", fingerprint(public_key)
    problems.append("SHA256SUMS SIGNATURE DOES NOT VERIFY: the file list was rewritten after export")
    return "invalid", fingerprint(public_key)


def check_for_extra_files(root, listed, problems):
    """Anything in the bundle that SHA256SUMS does not name.

    Without this, a file could simply be ADDED -- every listed hash still
    matches and nothing looks wrong.
    """
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel in NOT_IN_SUMS or rel in listed:
                continue
            problems.append(f"not listed in SHA256SUMS: {rel}")


def main(root):
    problems, checked = [], 0

    manifest_path = os.path.join(root, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("FAIL: manifest.json is missing. This is not a complete bundle.")
        return 2

    manifest_digest = sha256_file(manifest_path)
    print(f"manifest.json sha256 = {manifest_digest}")

    recorded = os.path.join(root, "MANIFEST.sha256")
    if os.path.isfile(recorded):
        with open(recorded, encoding="utf-8") as fh:
            parts = fh.read().strip().split()
        if not parts or parts[0] != manifest_digest:
            problems.append("MANIFEST.sha256 does not match manifest.json")

    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"FAIL: manifest.json is not readable JSON: {exc}")
        return 2

    sums_path = os.path.join(root, "SHA256SUMS")
    if not os.path.isfile(sums_path):
        print("FAIL: SHA256SUMS is missing.")
        return 2

    listed = set()
    with open(sums_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            expected, _, name = line.partition("  ")
            if unsafe(name):
                problems.append(f"refused unsafe path in SHA256SUMS: {name!r}")
                continue
            listed.add(name)
            target = os.path.join(root, name)
            if not os.path.isfile(target):
                problems.append(f"missing: {name}")
                continue
            checked += 1
            if sha256_file(target) != expected:
                problems.append(f"ALTERED since export: {name}")

    check_for_extra_files(root, listed, problems)

    # The manifest records what was sealed; SHA256SUMS records what is in the
    # bundle. Comparing the two is how "sealed but since altered" is caught.
    for control in manifest.get("controls", []):
        for item in control.get("evidence", []):
            path = item.get("path") or ""
            if not path:
                continue
            if unsafe(path):
                problems.append(f"refused unsafe path in manifest: {path!r}")
                continue
            target = os.path.join(root, path)
            if not os.path.isfile(target):
                problems.append(f"sealed evidence missing from bundle: {path}")
                continue
            if sha256_file(target) != item.get("sha256"):
                problems.append(
                    f"NOT THE SEALED BYTES: {path} "
                    f"(sealed {item.get('sha256', '')[:16]}…)"
                )

    signature, key_fp = check_signature(root, problems)
    sums_signature, sums_fp = check_sums_signature(root, problems)

    package = manifest.get("package", {})
    print(f"package      : {package.get('name', '?')}")
    print(f"sealed       : {package.get('sealed_at') or 'not sealed'} "
          f"by {package.get('sealed_by') or '?'}")
    prior = package.get("prior")
    if prior:
        print(f"predecessor  : {prior.get('name', '?')} (manifest {str(prior.get('manifest_sha256', ''))[:16]}…)")
    print(f"controls     : {manifest.get('totals', {}).get('controls', '?')}")
    print(f"evidence     : {manifest.get('totals', {}).get('evidence', '?')}")
    print(f"files checked: {checked}")
    if signature == "unsigned":
        print("signature    : none (compare the manifest digest with the one published to you)")
    else:
        print(f"signature    : {signature.upper()} (Ed25519, over manifest.json)")
        if key_fp:
            print(f"signing key  : {key_fp[:16]}  fingerprint sha256:{key_fp}")
    if sums_signature == "unsigned":
        print("bundle sig   : none (only manifest.json is covered by a signature)")
    else:
        print(f"bundle sig   : {sums_signature.upper()} (Ed25519, over SHA256SUMS)")
        if sums_fp and sums_fp != key_fp:
            print(f"exported by  : {sums_fp[:16]}  fingerprint sha256:{sums_fp}")

    if problems:
        print(f"\nFAIL — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nOK — every file matches both the bundle checksums and the sealed manifest.")
    if signature == "valid" and sums_signature == "valid":
        print("Both signatures verify: the sealed manifest, and the file list covering every")
        print("other member — including controls.csv and samples.csv, which hold the")
        print("conclusions recorded after the seal. Compare the fingerprint above with the one")
        print("the organisation published; if they match, the bundle is theirs and unchanged.")
    elif signature == "valid":
        print("The sealed manifest is signed and verifies. NOTE: this bundle carries no")
        print("signature over SHA256SUMS, so the files written after sealing — controls.csv,")
        print("samples.csv and trail.csv, which carry the auditor's conclusions — are covered")
        print("by checksums only. Their contents are consistent with this bundle, but nothing")
        print("proves the bundle itself was exported by the organisation.")
    else:
        print("This proves the contents are unchanged. It does not prove their origin:")
        print("compare the manifest digest above with the one published to you separately.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
