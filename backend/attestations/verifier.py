#!/usr/bin/env python3
"""
Verify a Conformiti evidence package. Shipped inside every bundle as verify.py.

    python3 verify.py .

Read-only and standard-library only. It opens files, hashes them and prints a
verdict; it extracts nothing, writes nothing and contacts nothing. Any path in
SHA256SUMS or in the manifest that is absolute or contains a ".." segment is
refused before it is opened.

What a pass means: the files beside this script are the files that were sealed.
What it does not mean: that they came from anyone in particular. This bundle
carries no signature. Compare the manifest digest below with the one the
organisation published to you separately.

Exit codes: 0 everything matches, 1 a mismatch, 2 the bundle is unusable.
"""
import hashlib
import json
import os
import sys

CHUNK = 64 * 1024


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

    with open(sums_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            expected, _, name = line.partition("  ")
            if unsafe(name):
                problems.append(f"refused unsafe path in SHA256SUMS: {name!r}")
                continue
            target = os.path.join(root, name)
            if not os.path.isfile(target):
                problems.append(f"missing: {name}")
                continue
            checked += 1
            if sha256_file(target) != expected:
                problems.append(f"ALTERED since export: {name}")

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

    package = manifest.get("package", {})
    print(f"package      : {package.get('name', '?')}")
    print(f"sealed       : {package.get('sealed_at') or 'not sealed'} "
          f"by {package.get('sealed_by') or '?'}")
    print(f"controls     : {manifest.get('totals', {}).get('controls', '?')}")
    print(f"evidence     : {manifest.get('totals', {}).get('evidence', '?')}")
    print(f"files checked: {checked}")

    if problems:
        print(f"\nFAIL — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nOK — every file matches both the bundle checksums and the sealed manifest.")
    print("This proves the contents are unchanged. It does not prove their origin:")
    print("compare the manifest digest above with the one published to you separately.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
