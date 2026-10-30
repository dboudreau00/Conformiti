"""The manifest, whose digest identifies a package: stdlib only, plain dicts in and out. Canonical form is sorted keys,
no whitespace, ASCII-escaped, LF-terminated, and equal inputs must give byte-identical output."""
import hashlib
import json
import os
import re

# Additive only: manifests of earlier versions, which lack the newer keys, must keep verifying.
MANIFEST_VERSION = 4
HASH_ALGORITHM = "sha256"


def canonical_bytes(payload):
    """Serialize to the one form whose digest is the package's identity."""
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def sha256_stream(fileobj, chunk_size=64 * 1024):
    digest = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(chunk_size), b""):
        digest.update(chunk)
    return digest.hexdigest()


def safe_segment(text):
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(text or "")).strip("_")
    return cleaned[:60] or "item"


def safe_member_name(document_name, storage_name, ordinal):
    """Stem from the document name, extension from the STORED basename: ``Document.name`` is free text, so taking the
    extension from it would let a validated PDF extract as ``index.html``."""
    stem = os.path.splitext(os.path.basename(str(document_name or "").replace("\\", "/")))[0]
    ext = os.path.splitext(os.path.basename(str(storage_name or "").replace("\\", "/")))[1]
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", stem).strip("._")
    stem = re.sub(r"\.{2,}", ".", stem)[:100] or "file"
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext)[:10]
    return f"{ordinal:03d}-{stem}{ext}"


def member_directory(control_ordinal, control_ref):
    return f"evidence/{control_ordinal:03d}-{safe_segment(control_ref)}"


def build_manifest(package, controls):
    """``package`` and ``controls`` carry snapshotted values only, never a live User, Document or Control: a rename or
    a deleted account after sealing must not change the digest."""
    payload = {
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
            # In the signed bytes: one key serves the installation, so the fingerprint alone does not name the tenant.
            "workspace": package.get("workspace"),
        },
        "totals": {
            "controls": len(controls),
            "evidence": sum(len(c["evidence"]) for c in controls),
            "samples": sum(len(c.get("samples") or []) for c in controls),
        },
        "controls": controls,
    }
    if package.get("prior"):
        payload["package"]["prior"] = package["prior"]
    return payload
