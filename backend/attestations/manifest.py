"""
The manifest: the one artefact an audit package is *about*.

Deliberately Django-free — stdlib only, plain dicts in, plain dict out. That is
not tidiness: the manifest's digest is the package's identity, so the code that
produces it must be reproducible years later, testable without a database, and
verifiable by ``tools/validate.py`` with nothing on the path but this directory.

Canonical form is sorted keys, no whitespace, ASCII-escaped, LF-terminated. Any
two runs over the same inputs must produce byte-identical output, or the digest
is meaningless.
"""
import hashlib
import json
import os
import re

MANIFEST_VERSION = 1
HASH_ALGORITHM = "sha256"


def canonical_bytes(payload):
    """Serialize to the one form whose digest is the package's identity."""
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def sha256_stream(fileobj, chunk_size=64 * 1024):
    """Digest a file-like object without holding it in memory."""
    digest = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(chunk_size), b""):
        digest.update(chunk)
    return digest.hexdigest()


def safe_segment(text):
    """A single path segment, safe on every filesystem a bundle may be opened on."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(text or "")).strip("_")
    return cleaned[:60] or "item"


def safe_member_name(document_name, storage_name, ordinal):
    """Build a member name; never reuse one supplied by a user.

    The stem comes from the human document name, the extension from the STORED
    basename. ``documents/uploads.py::validate_upload`` blocks .html/.svg/.js on
    the *uploaded* filename, but ``Document.name`` is free text — so taking the
    extension from the display name would let a validated PDF land in the
    auditor's extracted tree as ``index.html``.

    A document called ``../../etc/passwd.pdf`` becomes ``001-passwd.pdf``.
    """
    stem = os.path.splitext(os.path.basename(str(document_name or "").replace("\\", "/")))[0]
    ext = os.path.splitext(os.path.basename(str(storage_name or "").replace("\\", "/")))[1]
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem).strip("._")
    stem = re.sub(r"\.{2,}", ".", stem)[:100] or "file"
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext)[:10]
    return f"{ordinal:03d}-{stem}{ext}"


def member_directory(control_ordinal, control_ref):
    return f"evidence/{control_ordinal:03d}-{safe_segment(control_ref)}"


def build_manifest(package, controls):
    """Assemble the manifest from plain dictionaries.

    ``package`` and ``controls`` carry only values already snapshotted onto the
    package rows — never a live ``User``, ``Document`` or ``Control``. A rename
    or a deleted account after sealing must not change the digest.
    """
    return {
        "manifest_version": MANIFEST_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "generator": package["generator"],
        "package": {
            "id": package["id"],
            "name": package["name"],
            "engagement": package["engagement"],
            "audit_firm": package["audit_firm"],
            "assurance_type": package["assurance_type"],
            "assurance_type_label": package["assurance_type_label"],
            "framework": package["framework"],
            "scope": package["scope"],
            "scope_note": package["scope_note"],
            "period_start": package["period_start"],
            "period_end": package["period_end"],
            "assertion": package["assertion"],
            "asserted_by": package["asserted_by"],
            "asserted_at": package["asserted_at"],
            "sealed_by": package["sealed_by"],
            "sealed_at": package["sealed_at"],
            "created_by": package["created_by"],
            "created_at": package["created_at"],
        },
        "totals": {
            "controls": len(controls),
            "evidence": sum(len(c["evidence"]) for c in controls),
        },
        "controls": controls,
    }
