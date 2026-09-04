"""
Building the manifest and the export bundle.

Django-aware, unlike ``manifest.py``: this is where model rows become the plain
dictionaries the pure module hashes, and where bytes are streamed into a ZIP.
"""
import csv
import io
import zipfile
from pathlib import Path

from django.utils import timezone

from config.csvsafe import csv_safe

from . import manifest as mf
from .models import PackageEvidence

GENERATOR = "Conformiti"

VERIFIER = Path(__file__).with_name("verifier.py")


def _iso(value):
    return value.isoformat() if value else None


def control_payload(row):
    """One control row as the manifest sees it — snapshot values only."""
    return {
        "ordinal": row.ordinal,
        "framework_key": row.framework_key,
        "framework_name": row.framework_name,
        "framework_version": row.framework_version,
        "category_key": row.category_key,
        "category_name": row.category_name,
        "control_ref": row.control_ref,
        "title": row.title,
        "objective": row.objective,
        "management_status": row.mgmt_status,
        "management_status_label": row.mgmt_status_display,
        "owner": row.owner_name,
        "note": row.note,
        "included_by": row.included_by_name,
        "design_conclusion": row.design_conclusion,
        "operating_conclusion": row.operating_conclusion,
        "not_tested_reason": row.not_tested_reason,
        "auditor_note": row.auditor_note,
        "concluded_by": row.concluded_by_name,
        "concluded_at": _iso(row.concluded_at),
        "management_response": row.management_response,
        "evidence": [evidence_payload(e) for e in row.evidence.all()],
    }


def evidence_payload(row):
    """One artefact as the manifest sees it.

    Carries no folder path, no stored filename and no storage key: publishing
    those would hand back the unauthenticated route to the bytes that the
    authenticated-media work closed.
    """
    return {
        "ordinal": row.ordinal,
        "document": row.document_name,
        "version": row.pinned_version,
        "status": row.doc_status,
        "status_label": row.doc_status_display,
        "size_bytes": row.size_bytes,
        "hash_algorithm": row.hash_algorithm,
        "sha256": row.content_sha256,
        "last_reviewed": _iso(row.last_reviewed),
        "next_review_date": _iso(row.next_review_date),
        "covers_from": _iso(row.covers_from),
        "covers_to": _iso(row.covers_to),
        "is_population": row.is_population,
        "note": row.evidence_note,
        "linked_by": row.linked_by_name,
        "linked_at": _iso(row.evidence_linked_at),
        "pinned_by": row.pinned_by_name,
        "pinned_at": _iso(row.snapshot_at),
        "path": row.member_path,
    }


def package_payload(package):
    return {
        "id": package.pk,
        "name": package.name,
        "engagement": package.engagement,
        "audit_firm": package.audit_firm,
        "assurance_type": package.assurance_type,
        "assurance_type_label": package.get_assurance_type_display(),
        "framework": package.framework.key if package.framework_id else None,
        "scope": sorted(c.key for c in package.scope.all()),
        "scope_note": package.scope_note,
        "period_start": _iso(package.period_start),
        "period_end": _iso(package.period_end),
        "assertion": package.assertion,
        "asserted_by": package.asserted_by_name,
        "asserted_at": _iso(package.asserted_at),
        "sealed_by": package.sealed_by_name,
        "sealed_at": _iso(package.sealed_at),
        "created_by": package.created_by_name,
        "created_at": _iso(package.created_at),
        "generator": GENERATOR,
    }


def assign_paths(package):
    """Give every row its ordinal and bundle path. Called once, at seal.

    Doing it at seal rather than at export is what lets the manifest name a
    file before the bundle exists — and lets the bundle be regenerated later
    without changing the digest.
    """
    for c_index, control in enumerate(package.controls.all().order_by("control_ref", "pk"), start=1):
        control.ordinal = c_index
        control.save(update_fields=["ordinal"])
        directory = mf.member_directory(c_index, control.control_ref)
        for e_index, row in enumerate(control.evidence.all().order_by("document_name", "pk"), start=1):
            row.ordinal = e_index
            row.member_path = f"{directory}/{mf.safe_member_name(row.document_name, row.storage_name, e_index)}"
            row.save(update_fields=["ordinal", "member_path"])


def build_manifest(package):
    """The manifest dict for a package whose paths are already assigned."""
    controls = list(
        package.controls.all().prefetch_related("evidence").order_by("ordinal", "control_ref")
    )
    return mf.build_manifest(package_payload(package), [control_payload(c) for c in controls])


def _csv_bytes(header, rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow(csv_safe(row))
    return buffer.getvalue().encode("utf-8-sig")


def controls_csv(package):
    header = [
        "Framework", "Version", "Category", "Control ID", "Title", "Objective",
        "Management status at seal", "Design conclusion", "Operating conclusion",
        "Not-tested reason", "Concluded by", "Concluded at", "Auditor note",
        "Management response", "Evidence count", "Population source",
    ]
    rows = []
    for c in package.controls.all().prefetch_related("evidence"):
        evidence = list(c.evidence.all())
        rows.append([
            c.framework_name, c.framework_version, c.category_name, c.control_ref,
            c.title, c.objective, c.mgmt_status_display,
            c.get_design_conclusion_display(), c.get_operating_conclusion_display(),
            c.not_tested_reason, c.concluded_by_name, _iso(c.concluded_at) or "",
            c.auditor_note, c.management_response, len(evidence),
            "yes" if any(e.is_population for e in evidence) else "no",
        ])
    return _csv_bytes(header, rows)


def evidence_csv(package, actual):
    """``actual`` maps evidence id -> digest computed while writing the bundle."""
    header = [
        "Control ID", "Document", "Version at pin", "Document status at pin",
        "Covers from", "Covers to", "Population source", "Bytes",
        "SHA-256 at seal", "SHA-256 at export", "Integrity",
        "Pinned by", "Pinned at", "Linked by", "Linked at", "Evidence note",
        "Path in bundle",
    ]
    rows = []
    for row in PackageEvidence.objects.filter(
        package_control__package=package
    ).select_related("package_control").order_by("package_control__ordinal", "ordinal"):
        now = actual.get(row.pk)
        if now is None:
            verdict = "MISSING"
        elif now == row.content_sha256:
            verdict = "OK"
        else:
            verdict = "ALTERED"
        rows.append([
            row.package_control.control_ref, row.document_name, row.pinned_version,
            row.doc_status_display, _iso(row.covers_from) or "", _iso(row.covers_to) or "",
            "yes" if row.is_population else "no", row.size_bytes,
            row.content_sha256, now or "", verdict,
            row.pinned_by_name, _iso(row.snapshot_at) or "",
            row.linked_by_name, _iso(row.evidence_linked_at) or "",
            row.evidence_note, row.member_path,
        ])
    return _csv_bytes(header, rows)


def trail_csv(package):
    """The audit-trail extract.

    No IP addresses: this file is designed to leave the building, and staff
    network addresses have no business in it.
    """
    from audit.models import AuditLog

    header = ["Timestamp", "Actor", "Action", "Record type", "Record id", "Detail"]
    document_ids = {
        str(pk) for pk in PackageEvidence.objects.filter(
            package_control__package=package, document__isnull=False
        ).values_list("document_id", flat=True)
    }
    entries = AuditLog.objects.filter(object_type="documents", object_id__in=document_ids)
    if package.period_start:
        entries = entries.filter(timestamp__gte=package.period_start)
    rows = [
        [e.timestamp.isoformat(), e.user.get_username() if e.user_id else "",
         e.action, e.object_type, e.object_id, e.detail]
        for e in entries.order_by("timestamp")[:5000]
    ]
    return _csv_bytes(header, rows)


def readme_text(package, digest, summary):
    lines = [
        f"{package.name}",
        "=" * len(package.name),
        "",
        "An evidence package exported from Conformiti.",
        "",
        f"Engagement       {package.engagement or '-'}",
        f"Audit firm       {package.audit_firm or '-'}",
        f"Assurance type   {package.get_assurance_type_display()}",
        f"Framework        {package.framework.name if package.framework_id else '-'}",
        f"Period           {_iso(package.period_start) or '-'} to {_iso(package.period_end) or '-'}",
        f"Assembled by     {package.created_by_name} on {_iso(package.created_at)}",
        f"Sealed by        {package.sealed_by_name} on {_iso(package.sealed_at)}",
        f"Exported         {timezone.now().isoformat()}",
        "",
        f"Controls         {summary['controls']}",
        f"Evidence files   {summary['items']}",
        f"Not tested       {summary['not_tested']}",
        "",
        "MANAGEMENT ASSERTION",
        "--------------------",
        package.assertion or "(none recorded)",
        "",
        "SEGREGATION",
        "-----------",
        "Conclusions in controls.csv were recorded by the auditor named against",
        "each row. Nobody at the assessed organisation can edit them: the API",
        "accepts a conclusion only from the account the package was issued to.",
        "The management response column is the organisation's reply and is",
        "written by the organisation.",
        "",
        "VERIFYING THIS BUNDLE",
        "---------------------",
        "The manifest digest for this package is:",
        f"  {digest}",
        "",
        "1. Check the manifest against the digest published to you separately:",
        "     sha256sum manifest.json          (Windows: certutil -hashfile manifest.json SHA256)",
        "   It must equal the digest above and the one in MANIFEST.sha256.",
        "",
        "2. Check every file in this bundle:",
        "     sha256sum -c SHA256SUMS",
        "",
        "3. Optional, if your policy allows running a script received from a",
        "   client -- it is read-only, stdlib-only, and extracts nothing:",
        "     python3 verify.py .",
        "",
        "WHAT THIS DOES AND DOES NOT PROVE",
        "---------------------------------",
        "The digests prove the files in this bundle are the files that were",
        "sealed. They do NOT prove who produced them: this bundle carries no",
        "cryptographic signature, so anyone able to rewrite the bundle could",
        "rewrite manifest.json, SHA256SUMS and MANIFEST.sha256 consistently.",
        "The binding to a moment is the seal entry in the organisation's audit",
        "trail, which records this digest, and the digest you were given out of",
        "band. Compare them.",
        "",
        "Access to the live package expires; this bundle does not. Treat it as",
        "the confidential material it is.",
        "",
        "INTEGRITY AT EXPORT",
        "-------------------",
        summary["integrity_line"],
        "",
    ]
    return ("\n".join(lines)).encode("utf-8")


def write_bundle(package, fh):
    """Stream the ZIP into ``fh``. Returns a summary dict."""
    rows = list(
        PackageEvidence.objects.filter(package_control__package=package)
        .select_related("package_control", "document")
        .order_by("package_control__ordinal", "ordinal")
    )
    sealed_at = package.sealed_at or timezone.now()
    stamp = (sealed_at.year, sealed_at.month, sealed_at.day,
             sealed_at.hour, sealed_at.minute, sealed_at.second)

    actual = {}
    members = {}

    with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
        def write(name, data):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
            members[name] = mf.sha256_hex(data)

        # Evidence first: writing streams the bytes and gives us the digests
        # every later member reports on.
        for row in rows:
            if not row.member_path:
                continue
            digest = None
            if row.document and row.document.file:
                info = zipfile.ZipInfo(row.member_path, date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                try:
                    source = row.document.file.open("rb")
                except (FileNotFoundError, OSError, ValueError):
                    source = None
                if source is not None:
                    import hashlib
                    sha = hashlib.sha256()
                    try:
                        with zf.open(info, "w") as target:
                            for chunk in iter(lambda: source.read(64 * 1024), b""):
                                sha.update(chunk)
                                target.write(chunk)
                    finally:
                        source.close()
                    digest = sha.hexdigest()
                    members[row.member_path] = digest
            actual[row.pk] = digest

        altered = sum(1 for r in rows if actual.get(r.pk) not in (None, r.content_sha256))
        missing = sum(1 for r in rows if actual.get(r.pk) is None)
        not_tested = package.controls.filter(
            design_conclusion="not_tested").count()
        if altered or missing:
            integrity_line = (
                f"DISCREPANCIES: {altered} altered, {missing} missing. "
                "The bytes in this bundle are NOT the bytes that were sealed. "
                "See the Integrity column in evidence.csv."
            )
        else:
            integrity_line = "OK: every file matches the digest recorded when the package was sealed."

        summary = {
            "items": len(rows), "altered": altered, "missing": missing,
            "controls": package.controls.count(), "not_tested": not_tested,
            "integrity_line": integrity_line,
        }

        # The sealed manifest, byte-for-byte as it was stored.
        manifest_bytes = (package.manifest_json or "").encode("utf-8")
        if not manifest_bytes:
            manifest_bytes = mf.canonical_bytes(build_manifest(package))
        digest = mf.sha256_hex(manifest_bytes)
        write("manifest.json", manifest_bytes)
        write("MANIFEST.sha256", f"{digest}  manifest.json\n".encode("utf-8"))

        write("controls.csv", controls_csv(package))
        write("evidence.csv", evidence_csv(package, actual))
        write("trail.csv", trail_csv(package))
        write("INTEGRITY.txt", (integrity_line + "\n").encode("utf-8"))
        write("README.txt", readme_text(package, digest, summary))
        try:
            write("verify.py", VERIFIER.read_bytes())
        except OSError:
            pass

        # Last, so it can describe everything else.
        checksums = "".join(
            f"{members[name]}  {name}\n" for name in sorted(members)
        ).encode("utf-8")
        zf.writestr(zipfile.ZipInfo("SHA256SUMS", date_time=stamp), checksums)

    summary["manifest_sha256"] = digest
    return summary
