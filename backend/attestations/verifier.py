#!/usr/bin/env python3
"""Verify a Conformiti evidence package (verify.py in every bundle):
python3 verify.py [--allow-unsigned] [--trust KEY]... [DIRECTORY].
KEY is a public key file or a 64-character sha256 fingerprint the organisation gave you; repeat the option to trust
several (an export made after a key rotation carries two). Read-only, standard library only.
Exit codes: 0 all match; 1 mismatch, or a signing key you did not trust; 2 unusable bundle; 3 matches but unsigned."""
import base64
import hashlib
import json
import os
import stat
import sys

CHUNK = 64 * 1024

# Ed25519 (RFC 8032), verification only
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
    if x == 0 and sign:
        raise ValueError("bad point")      # RFC 8032 5.1.3: -0 is not an encoding
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
    """True when the 64-byte ``signature`` is valid for ``message`` under the raw 32-byte ``public_key``."""
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


def _safe(value):
    """Bundle text with anything a terminal would act on written out: a forged name could carry an escape sequence
    that hides the real FAIL."""
    return "".join(
        ch if ch.isprintable()
        else ("%sx%02x" % (chr(92), ord(ch)) if ord(ch) < 256 else "%su%04x" % (chr(92), ord(ch)))
        for ch in str(value))


def fingerprint(public_key):
    return hashlib.sha256(public_key).hexdigest()


def unsafe(path):
    """Reject anything that could escape the bundle directory."""
    if not path or path.startswith(("/", "\\")):
        return True
    if len(path) > 1 and path[1] == ":":
        return True
    parts = path.replace("\\", "/").split("/")
    return any(p in ("..", "") for p in parts)


def plain_file(root, name):
    """True when ``name`` under ``root`` is a regular file reached through no symlink. A link would let a bundle point
    the check at another file, or at /dev/zero, which never ends."""
    path = root
    parts = name.replace("\\", "/").split("/")
    for index, part in enumerate(parts):
        path = os.path.join(path, part)
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            return False
        if stat.S_ISLNK(mode):
            return False
        if not (stat.S_ISREG(mode) if index == len(parts) - 1 else stat.S_ISDIR(mode)):
            return False
    return True


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise OSError(f"{path} is not a regular file")
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_or_none(path):
    """The file's sha256, or None when it cannot be read as a regular file (so it matches nothing)."""
    try:
        return sha256_file(path)
    except OSError:
        return None


def check_signature(root, problems):
    """Returns (status, fingerprint): 'valid', 'invalid', 'unsigned' or 'unusable'."""
    sig_path = os.path.join(root, "manifest.sig")
    key_path = os.path.join(root, "signing-key.pub")
    if not os.path.lexists(sig_path):
        return "unsigned", None
    if not plain_file(root, "manifest.sig"):
        problems.append("manifest.sig is not a regular file")
        return "unusable", None
    if not os.path.lexists(key_path):
        problems.append("manifest.sig is present but signing-key.pub is missing")
        return "unusable", None
    if not plain_file(root, "signing-key.pub"):
        problems.append("signing-key.pub is not a regular file")
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
    """Like ``check_signature`` for SHA256SUMS, whose signature covers the files written after the seal
    (controls.csv, samples.csv)."""
    sig_path = os.path.join(root, "SHA256SUMS.sig")
    key_path = os.path.join(root, "sums-key.pub")
    if not os.path.lexists(sig_path):
        return "unsigned", None
    if not plain_file(root, "SHA256SUMS.sig"):
        problems.append("SHA256SUMS.sig is not a regular file")
        return "unusable", None
    if not os.path.lexists(key_path):
        problems.append("SHA256SUMS.sig is present but sums-key.pub is missing")
        return "unusable", None
    if not plain_file(root, "sums-key.pub"):
        problems.append("sums-key.pub is not a regular file")
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


def check_keys(signature, key_fp, sums_signature, sums_fp, trusted, problems):
    """Which key signed what. The key shipped inside a bundle proves nothing about who made it, so two signatures
    under different keys are a problem unless the reader trusted the second key, and with ``--trust`` every
    signature must come from a key the reader named."""
    manifest_key = key_fp if signature == "valid" else None
    sums_key = sums_fp if sums_signature == "valid" else None
    if manifest_key and sums_key and manifest_key != sums_key and sums_key not in trusted:
        problems.append(
            f"SHA256SUMS IS SIGNED BY A DIFFERENT KEY than manifest.json: {sums_key[:16]} against {manifest_key[:16]}. "
            "The sums key travels inside the bundle, so a forger can supply one. An honest export made after the "
            "organisation rotated its signing key looks the same: ask them to confirm both keys, "
            f"sha256:{manifest_key} and sha256:{sums_key}, and re-run with "
            f"--trust sha256:{manifest_key} --trust sha256:{sums_key}")
    if not trusted:
        return
    for label, state, fp in (("manifest.json", signature, manifest_key), ("SHA256SUMS", sums_signature, sums_key)):
        if state == "unsigned":
            problems.append(f"--trust was given but {label} carries no signature")
        elif fp and fp not in trusted:
            problems.append(f"{label} is signed by key {fp[:16]}, which is not one of the keys given to --trust")


def check_for_extra_files(root, listed, problems):
    """Report files SHA256SUMS does not name: a file ADDED to the bundle would otherwise go unnoticed."""
    for base, dirs, files in os.walk(root):
        for name in dirs:
            full = os.path.join(base, name)
            if os.path.islink(full):
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                problems.append(f"refused a symbolic link to a directory: {rel}")
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if rel in NOT_IN_SUMS or rel in listed:
                continue
            problems.append(f"not listed in SHA256SUMS: {rel}")


def main(root, allow_unsigned=False, trusted=()):
    """``trusted`` holds sha256 fingerprints (hex) of the keys the reader got from the organisation."""
    problems, checked = [], 0
    trusted = {fp.lower() for fp in trusted}

    manifest_path = os.path.join(root, "manifest.json")
    if not plain_file(root, "manifest.json"):
        if os.path.lexists(manifest_path):
            print("FAIL: manifest.json is not a regular file. This is not a bundle this program will read.")
        else:
            print("FAIL: manifest.json is missing. This is not a complete bundle.")
        return 2

    manifest_digest = sha256_file(manifest_path)
    print(f"manifest.json sha256 = {manifest_digest}")

    recorded = os.path.join(root, "MANIFEST.sha256")
    if os.path.lexists(recorded):
        if not plain_file(root, "MANIFEST.sha256"):
            problems.append("MANIFEST.sha256 is not a regular file")
        else:
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
    if not plain_file(root, "SHA256SUMS"):
        print("FAIL: SHA256SUMS is missing." if not os.path.lexists(sums_path)
              else "FAIL: SHA256SUMS is not a regular file.")
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
            if not plain_file(root, name):
                problems.append(f"refused, not a regular file: {name}" if os.path.lexists(target)
                                else f"missing: {name}")
                continue
            checked += 1
            if digest_or_none(target) != expected:
                problems.append(f"ALTERED since export: {name}")

    check_for_extra_files(root, listed, problems)

    # The manifest records what was sealed, SHA256SUMS what is in the bundle: comparing the two catches alteration.
    for control in manifest.get("controls", []):
        for item in control.get("evidence", []):
            path = item.get("path") or ""
            if not path:
                continue
            if unsafe(path):
                problems.append(f"refused unsafe path in manifest: {path!r}")
                continue
            target = os.path.join(root, path)
            if not plain_file(root, path):
                problems.append(f"sealed evidence is not a regular file: {path}" if os.path.lexists(target)
                                else f"sealed evidence missing from bundle: {path}")
                continue
            if digest_or_none(target) != item.get("sha256"):
                problems.append(
                    f"NOT THE SEALED BYTES: {path} "
                    f"(sealed {item.get('sha256', '')[:16]}…)"
                )

    signature, key_fp = check_signature(root, problems)
    sums_signature, sums_fp = check_sums_signature(root, problems)
    check_keys(signature, key_fp, sums_signature, sums_fp, trusted, problems)

    package = manifest.get("package", {})
    print(f"package      : {_safe(package.get('name', '?'))}")
    print(f"sealed       : {_safe(package.get('sealed_at') or 'not sealed')} "
          f"by {_safe(package.get('sealed_by') or '?')}")
    prior = package.get("prior")
    if prior:
        print(f"predecessor  : {_safe(prior.get('name', '?'))} "
              f"(manifest {_safe(str(prior.get('manifest_sha256', ''))[:16])}…)")
    print(f"controls     : {_safe(manifest.get('totals', {}).get('controls', '?'))}")
    print(f"evidence     : {_safe(manifest.get('totals', {}).get('evidence', '?'))}")
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
            print(f"exported by  : {sums_fp[:16]}  fingerprint sha256:{sums_fp}  (a different key)")

    if problems:
        print(f"\nFAIL: {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {_safe(problem)}")
        return 1

    missing = [name for name, state in (("manifest.sig", signature),
                                        ("SHA256SUMS.sig", sums_signature))
               if state == "unsigned"]
    # Exit 3, not 0: with the signatures stripped and the file list rewritten, every checksum still agrees with itself.
    if missing and not allow_unsigned:
        print(f"\nUNSIGNED: {' and '.join(missing)} missing.")
        print("Every file matches its checksum, but nothing proves who produced this bundle,")
        print("and a file list without a signature can be rewritten to match any change.")
        print("Compare the manifest digest above with the one the organisation gave you")
        print("directly, and re-run with --allow-unsigned to accept the bundle deliberately.")
        return 3

    print("\nOK: every file matches both the bundle checksums and the sealed manifest.")
    if signature == "valid" and sums_signature == "valid":
        print("Both signatures verify: the sealed manifest, and the file list covering every")
        print("other member, including controls.csv and samples.csv, which hold the")
        print("conclusions recorded after the seal.")
        if trusted:
            print("Each was made by a key you named with --trust, so the bundle comes from whoever")
            print("holds that key and has not changed since it was exported.")
        else:
            print("That shows the bundle is consistent and was signed by one key; it does not show")
            print("whose key that is, because the key travels inside the bundle. Compare the")
            print("fingerprint above with the one the organisation gave you, or run this again with")
            print(f"--trust {key_fp}")
    elif signature == "valid":
        print("The sealed manifest is signed and verifies. NOTE: this bundle carries no")
        print("signature over SHA256SUMS, so the files written after sealing (controls.csv,")
        print("samples.csv and trail.csv, which carry the auditor's conclusions) are covered")
        print("by checksums only. Their contents are consistent with this bundle, but nothing")
        print("proves the bundle itself was exported by the organisation.")
    else:
        print("This proves the contents are unchanged. It does not prove their origin:")
        print("compare the manifest digest above with the one published to you separately.")
    return 0


USAGE = "usage: verify.py [--allow-unsigned] [--trust KEY]... [DIRECTORY]"


def trusted_fingerprint(value):
    """The sha256 fingerprint (hex) for a --trust argument: a public key file, or the fingerprint itself."""
    if os.path.isfile(value):
        with open(value, encoding="utf-8") as fh:
            return fingerprint(read_public_key(fh.read()))
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return text
    raise ValueError(f"--trust takes a public key file or a full 64-character sha256 fingerprint, not {value!r}")


def parse_args(argv):
    """``(directory, allow_unsigned, trusted)``; ValueError carries the message for a bad command line."""
    directory, allow_unsigned, trusted = [], False, []
    items = list(argv)
    while items:
        item = items.pop(0)
        if item == "--allow-unsigned":
            allow_unsigned = True
        elif item == "--trust" or item.startswith("--trust="):
            if item == "--trust":
                if not items:
                    raise ValueError("--trust needs a public key file or a sha256 fingerprint")
                item = items.pop(0)
            else:
                item = item[len("--trust="):]
            try:
                trusted.append(trusted_fingerprint(item))
            except (OSError, ValueError) as exc:
                raise ValueError(str(exc))
        elif item.startswith("--"):
            raise ValueError(f"unknown option {_safe(item)}")
        else:
            directory.append(item)
    if len(directory) > 1:
        raise ValueError("give one directory")
    return (directory[0] if directory else "."), allow_unsigned, trusted


if __name__ == "__main__":
    try:
        bundle_dir, unsigned_ok, trusted_keys = parse_args(sys.argv[1:])
    except ValueError as exc:
        print(USAGE)
        print(f"  {exc}")
        sys.exit(2)
    sys.exit(main(bundle_dir, allow_unsigned=unsigned_ok, trusted=trusted_keys))
