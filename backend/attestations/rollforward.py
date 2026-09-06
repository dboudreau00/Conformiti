"""
Roll-forward: this year's package from last year's, and the diff between them.

An auditor's first question on a repeat engagement is "what changed since
last time?" -- which controls entered or left scope, which evidence was
replaced, which of last year's exceptions are still open. ``diff`` answers
that from the two packages' own snapshots, so it works years later against
sealed rows and never reads a live control. ``roll_forward`` starts the new
draft from the sealed one: same engagement shape, the same controls
re-snapshotted as they stand today, with today's linked evidence pinned, and
``prior_package`` set so the diff is available from the first minute.
"""
from django.db import transaction

from documents.access import accessible_folder_ids

from .models import EvidencePackage
from .snapshot import pin_document, snapshot_control


def chain(package):
    """Every predecessor, nearest first. Bounded, so a cycle written by hand
    into the database cannot hang a request."""
    out, seen, current = [], {package.pk}, package.prior_package
    while current is not None and current.pk not in seen and len(out) < 50:
        out.append(current)
        seen.add(current.pk)
        current = current.prior_package
    return out


def would_cycle(package, prior):
    """True if making ``prior`` the predecessor of ``package`` closes a loop."""
    if prior is None:
        return False
    if prior.pk == package.pk:
        return True
    return any(p.pk == package.pk for p in chain(prior))


def _evidence_key(row):
    """How two pinned artefacts are matched across years: the live document
    when both still point at one, else the name."""
    return ("doc", row.document_id) if row.document_id else ("name", row.document_name)


def _control_key(row):
    return ("ctl", row.control_id) if row.control_id else ("ref", row.framework_key, row.control_ref)


def _evidence_diff(current, prior):
    cur = {_evidence_key(e): e for e in current.evidence.all()}
    old = {_evidence_key(e): e for e in prior.evidence.all()}
    added = [cur[k] for k in cur if k not in old]
    removed = [old[k] for k in old if k not in cur]
    changed, same = [], []
    for k in cur:
        if k not in old:
            continue
        if cur[k].content_sha256 != old[k].content_sha256:
            changed.append((old[k], cur[k]))
        else:
            same.append(cur[k])
    return added, removed, changed, same


def _ev(row):
    return {"id": row.pk, "document": row.document_name, "version": row.pinned_version,
            "sha256": row.content_sha256}


def diff(package):
    """The year-over-year comparison against ``package.prior_package``.

    Returns None when there is no prior. Everything comes from snapshot
    columns on the two packages' rows.
    """
    prior = package.prior_package
    if prior is None:
        return None
    cur_rows = {_control_key(r): r for r in package.controls.all().prefetch_related("evidence", "samples")}
    old_rows = {_control_key(r): r for r in prior.controls.all().prefetch_related("evidence", "samples")}

    added = [cur_rows[k] for k in cur_rows if k not in old_rows]
    removed = [old_rows[k] for k in old_rows if k not in cur_rows]
    kept = []
    totals = {"evidence_added": 0, "evidence_removed": 0, "evidence_changed": 0, "evidence_same": 0,
              "prior_exceptions": 0, "prior_exceptions_open": 0}
    for k, row in cur_rows.items():
        old = old_rows.get(k)
        if old is None:
            continue
        e_added, e_removed, e_changed, e_same = _evidence_diff(row, old)
        totals["evidence_added"] += len(e_added)
        totals["evidence_removed"] += len(e_removed)
        totals["evidence_changed"] += len(e_changed)
        totals["evidence_same"] += len(e_same)
        prior_exception = "exceptions" in (old.design_conclusion, old.operating_conclusion)
        if prior_exception:
            totals["prior_exceptions"] += 1
            # Open until this year's auditor concludes otherwise.
            if "no_exceptions" not in (row.design_conclusion, row.operating_conclusion):
                totals["prior_exceptions_open"] += 1
        kept.append({
            "id": row.pk, "prior_id": old.pk, "control_ref": row.control_ref, "title": row.title,
            "status_then": old.mgmt_status_display, "status_now": row.mgmt_status_display,
            "owner_then": old.owner_name, "owner_now": row.owner_name,
            "prior_design_conclusion": old.design_conclusion,
            "prior_operating_conclusion": old.operating_conclusion,
            "prior_auditor_note": old.auditor_note,
            "prior_exception": prior_exception,
            "prior_samples": old.samples.count(), "samples": row.samples.count(),
            "evidence": {
                "added": [_ev(e) for e in e_added],
                "removed": [_ev(e) for e in e_removed],
                "changed": [{"then": _ev(a), "now": _ev(b)} for a, b in e_changed],
                "same": len(e_same),
            },
        })
    kept.sort(key=lambda r: r["control_ref"])

    def scope(pkg):
        return sorted(c.key for c in pkg.scope.all())

    return {
        "prior": {
            "id": prior.pk, "name": prior.name, "status": prior.status,
            "engagement": prior.engagement, "period_start": prior.period_start,
            "period_end": prior.period_end, "sealed_at": prior.sealed_at,
            "manifest_sha256": prior.manifest_sha256,
        },
        "scope": {
            "added": sorted(set(scope(package)) - set(scope(prior))),
            "removed": sorted(set(scope(prior)) - set(scope(package))),
        },
        "controls": {
            "added": [{"id": r.pk, "control_ref": r.control_ref, "title": r.title} for r in
                      sorted(added, key=lambda r: r.control_ref)],
            "removed": [{"id": r.pk, "control_ref": r.control_ref, "title": r.title,
                         "prior_design_conclusion": r.design_conclusion,
                         "prior_operating_conclusion": r.operating_conclusion} for r in
                        sorted(removed, key=lambda r: r.control_ref)],
            "kept": kept,
        },
        "totals": {
            "controls_added": len(added), "controls_removed": len(removed), "controls_kept": len(kept),
            **totals,
        },
    }


def roll_forward(prior, user, name=None, engagement=None):
    """Open next year's draft from a sealed (or withdrawn) package.

    Controls are re-snapshotted as they stand today, with today's linked
    evidence pinned where the person can see it; the auditor's conclusions,
    samples and the request list are NOT copied -- they belong to the
    engagement they were made in.
    """
    if prior.status == EvidencePackage.Status.DRAFT:
        raise ValueError("Roll forward from a sealed package; a draft has nothing fixed to roll from.")
    full = (user.get_full_name() or user.get_username())[:200]
    visible = accessible_folder_ids(user)
    skipped = []
    with transaction.atomic():
        package = EvidencePackage.objects.create(
            name=(name or f"{prior.name} (roll-forward)")[:160],
            engagement=(engagement if engagement is not None else prior.engagement)[:160],
            audit_firm=prior.audit_firm, framework=prior.framework,
            assurance_type=prior.assurance_type, scope_note=prior.scope_note,
            prior_package=prior, created_by=user, created_by_name=full,
        )
        package.scope.set(prior.scope.all())
        for old in prior.controls.select_related("control__category__framework").order_by("ordinal", "control_ref"):
            control = old.control
            if control is None:
                # The control was deleted since; carry the reference forward
                # as a row with no live link so the diff can still name it.
                continue
            row = snapshot_control(package, control, user, note=old.note)
            for link in control.evidence_links.select_related("document", "linked_by"):
                if link.document.folder_id not in visible:
                    skipped.append({"control": control.control_id, "document": link.document.name,
                                    "reason": "not visible to you"})
                    continue
                pin_document(row, link.document, user, link=link)
    return package, skipped
