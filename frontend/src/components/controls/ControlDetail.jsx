import { useEffect, useMemo, useState } from "react";
import { PaperclipIcon } from "lucide-react";
import api, { fetchAll } from "../../api/client.js";
import { errorText } from "../../utils/a11y.js";
import { cn } from "../../utils/cn.js";
import { CONTROL_STATUS, DOC_STATUS, READINESS_BAND } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { Label, Loading } from "../ui/Panel.jsx";

const STATUS_KEYS = Object.keys(CONTROL_STATUS);

/** Expanded body of a control register row: objective, status/owner fields,
 * the linked-evidence list and the attach form. Mounted only while the row is
 * open, so evidence state starts fresh on every expand.
 *
 * Write controls are gated on the same capabilities the API enforces:
 *   status / owner   -> manage_frameworks (PATCH /controls/{id}/ 403s otherwise)
 *   attach evidence  -> manage_frameworks || manage_documents
 *   unlink           -> link.can_unlink (server-computed per link)
 */
export function ControlDetail({
  control,
  canManage,
  canLink,
  users,
  docChoices,
  choicesError,
  onPatch,
  onEvidenceDelta,
}) {
  const [links, setLinks] = useState([]);
  const [linksLoading, setLinksLoading] = useState(true);
  const [linksError, setLinksError] = useState("");
  const [selDocs, setSelDocs] = useState([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false); // attach / unlink in flight
  const [saving, setSaving] = useState(false); // status / owner PATCH in flight
  const [notice, setNotice] = useState(null); // { ok?, warn?, err?, skipped? }

  const id = control.id;

  async function loadLinks(alive = () => true) {
    try {
      const rows = await fetchAll(`/control-evidence/?control=${id}`);
      if (alive()) setLinks(rows);
    } catch (e) {
      if (alive()) setLinksError(errorText(e, "Couldn't load linked evidence."));
    } finally {
      if (alive()) setLinksLoading(false);
    }
  }

  useEffect(() => {
    let alive = true;
    setLinksLoading(true);
    setLinksError("");
    loadLinks(() => alive);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const [readiness, setReadiness] = useState(null);
  useEffect(() => {
    let alive = true;
    api.get(`/controls/${id}/readiness/`)
      .then(({ data }) => { if (alive) setReadiness(data); })
      .catch(() => { if (alive) setReadiness(null); });
    return () => { alive = false; };
  }, [id]);

  const linkedIds = useMemo(() => new Set(links.map((l) => l.document)), [links]);
  const available = useMemo(
    () => (docChoices || []).filter((d) => !linkedIds.has(d.id)),
    [docChoices, linkedIds]
  );
  const docName = (docId) => {
    const d = (docChoices || []).find((x) => x.id === docId);
    return d ? d.name : `Document #${docId}`;
  };

  async function patch(field, value) {
    setSaving(true);
    setNotice(null);
    try {
      await onPatch(id, { [field]: value });
      setNotice({ ok: {
        status: "Status updated.",
        owner: "Owner updated.",
        last_tested_on: "Test date recorded.",
        test_interval_days: "Test interval updated.",
      }[field] || "Saved." });
    } catch (e) {
      setNotice({ err: errorText(e) });
    } finally {
      setSaving(false);
    }
  }

  async function attach(e) {
    e.preventDefault();
    if (!selDocs.length) return;
    setBusy(true);
    setNotice(null);
    try {
      const { data } = await api.post("/control-evidence/bulk/", {
        control: id,
        documents: selDocs.map(Number),
        note,
      });
      const created = data.created || [];
      const skipped = data.skipped || [];
      if (created.length) onEvidenceDelta(id, created.length);
      setSelDocs([]);
      setNote("");
      // Re-read the list so each new link carries its server-computed
      // can_unlink flag (the bulk response is serialized without it).
      await loadLinks();
      setNotice({
        ok: `${created.length} attached`,
        skipped: skipped.map((s) => `${docName(s.document)} — ${s.reason}`),
      });
    } catch (ex) {
      setNotice({ err: errorText(ex) });
    } finally {
      setBusy(false);
    }
  }

  async function unlink(link) {
    setBusy(true);
    setNotice(null);
    try {
      await api.delete(`/control-evidence/${link.id}/`);
      setLinks((ls) => ls.filter((l) => l.id !== link.id));
      onEvidenceDelta(id, -1);
      setNotice({ ok: `Unlinked ${link.document_name}.` });
    } catch (ex) {
      setNotice({ err: errorText(ex) });
    } finally {
      setBusy(false);
    }
  }

  const statusMeta = CONTROL_STATUS[control.status] || { label: control.status, tone: "muted" };
  const ownerSelectable = canManage && Array.isArray(users);

  return (
    <div className="grid grid-cols-1 gap-6 px-5 py-4 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* ---- Left: readiness + objective + assignment ----------------------- */}
      <div className="space-y-4">
        {readiness ? <ReadinessBreakdown readiness={readiness} /> : null}
        <div>
          <Label className="mb-1.5 block">Objective</Label>
          <p className="text-[13px] leading-relaxed text-ink">{control.objective || "—"}</p>
          <p className="mt-1.5 text-xs text-muted">
            {control.framework}
            {control.category_name ? ` · ${control.category_name}` : ""}
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            {canManage ? (
              <>
                <label htmlFor={`control-status-${id}`} className="field-label">Status</label>
                <select
                  id={`control-status-${id}`}
                  className="input input-sm"
                  value={control.status}
                  disabled={saving}
                  onChange={(e) => patch("status", e.target.value)}
                >
                  {STATUS_KEYS.map((k) => (
                    <option key={k} value={k}>{CONTROL_STATUS[k].label}</option>
                  ))}
                </select>
              </>
            ) : (
              <>
                <Label className="mb-1.5 block">Status</Label>
                <Badge tone={statusMeta.tone} dot>{statusMeta.label}</Badge>
              </>
            )}
          </div>
          <div>
            {ownerSelectable ? (
              <>
                <label htmlFor={`control-owner-${id}`} className="field-label">Owner</label>
                <select
                  id={`control-owner-${id}`}
                  className="input input-sm"
                  value={control.owner ?? ""}
                  disabled={saving}
                  onChange={(e) => patch("owner", e.target.value === "" ? null : Number(e.target.value))}
                >
                  <option value="">Unassigned</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{u.full_name || u.username}</option>
                  ))}
                </select>
              </>
            ) : (
              <>
                <Label className="mb-1.5 block">Owner</Label>
                <p className={cn("text-[13px]", control.owner_name ? "text-ink" : "text-danger")}>
                  {control.owner_name || "Unassigned"}
                </p>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ---- Right: evidence ---------------------------------------------- */}
      <div className="space-y-4">
        {notice?.ok ? <div className="notice notice-ok" role="status">{notice.ok}</div> : null}
        {notice?.skipped?.length ? (
          <div className="notice notice-warn" role="status">
            <p className="font-medium">{notice.skipped.length} skipped</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs">
              {notice.skipped.map((s, i) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        ) : null}
        {notice?.err ? <div className="notice notice-err" role="alert">{notice.err}</div> : null}

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <Label>Linked evidence</Label>
            <Label className="tabular">{links.length}</Label>
          </div>
          {linksLoading ? (
            <Loading className="py-4">Loading evidence…</Loading>
          ) : linksError ? (
            <div className="notice notice-err" role="alert">{linksError}</div>
          ) : links.length === 0 ? (
            <p className="text-xs text-danger">No evidence attached.</p>
          ) : (
            <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
              {links.map((l) => {
                const ds = DOC_STATUS[l.document_status] || { label: l.document_status, tone: "muted" };
                return (
                  <li key={l.id} className="flex items-start gap-3 px-3 py-2.5">
                    <PaperclipIcon className="mt-1 h-3.5 w-3.5 shrink-0 text-faint" strokeWidth={2} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-[13px] font-medium text-ink">{l.document_name}</span>
                        <Badge tone={ds.tone} dot>{ds.label}</Badge>
                      </div>
                      <p className="truncate font-mono text-2xs text-faint">{l.folder_path}</p>
                      {l.note ? <p className="mt-1 text-xs text-muted">{l.note}</p> : null}
                      {l.linked_by_name ? <p className="mt-0.5 text-2xs text-faint">Linked by {l.linked_by_name}</p> : null}
                    </div>
                    {l.can_unlink ? (
                      <Button size="sm" variant="ghost" onClick={() => unlink(l)} disabled={busy} aria-label={`Unlink ${l.document_name}`}>
                        Unlink
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {canLink ? (
          <form onSubmit={attach} className="rounded-lg border border-line bg-surface p-3">
            <Label className="mb-2 block">Attach evidence</Label>
            {choicesError ? <div className="notice notice-err mb-2" role="alert">{choicesError}</div> : null}
            {!docChoices && !choicesError ? (
              <Loading className="py-3">Loading documents…</Loading>
            ) : (
              <>
                <label htmlFor={`attach-docs-${id}`} className="field-label">Documents</label>
                {available.length === 0 ? (
                  <p className="text-xs text-muted">Every document you can see is already linked to this control.</p>
                ) : (
                  <>
                    <select
                      id={`attach-docs-${id}`}
                      multiple
                      className="input h-auto min-h-[112px] py-1 font-mono text-xs"
                      value={selDocs}
                      onChange={(e) => setSelDocs(Array.from(e.target.selectedOptions).map((o) => o.value))}
                    >
                      {available.map((d) => (
                        <option key={d.id} value={d.id}>{d.path} / {d.name}</option>
                      ))}
                    </select>
                    <p className="mt-1 text-2xs text-faint">Hold Ctrl / ⌘ to select several documents.</p>
                  </>
                )}
                <div className="mt-3 flex flex-wrap items-end gap-2">
                  <div className="min-w-[200px] flex-1">
                    <label htmlFor={`attach-note-${id}`} className="field-label">Note (optional)</label>
                    <input
                      id={`attach-note-${id}`}
                      className="input input-sm"
                      value={note}
                      maxLength={255}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="Why this document applies"
                    />
                  </div>
                  <Button type="submit" variant="primary" size="sm" disabled={busy || !selDocs.length}>
                    {busy
                      ? "Attaching…"
                      : selDocs.length
                        ? `Attach ${selDocs.length} ${selDocs.length === 1 ? "document" : "documents"}`
                        : "Attach"}
                  </Button>
                </div>
              </>
            )}
          </form>
        ) : null}
      </div>
    </div>
  );
}


/** Why a control scores what it scores.

 * A bare number invites arguing with it; the breakdown turns "68" into a list
 * of the specific things that would move it, which is the only version of this
 * a control owner can act on.
 */
function ReadinessBreakdown({ readiness }) {
  const band = READINESS_BAND[readiness.band] || READINESS_BAND.not_started;
  if (readiness.score === null) {
    return (
      <div className="rounded-xl border border-line bg-surface p-3">
        <Label as="p">Readiness</Label>
        <p className="mt-1 text-xs text-muted">
          Marked not applicable, so it is excluded from every readiness figure.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="flex items-baseline justify-between gap-2">
        <Label as="p">Readiness</Label>
        <span className="flex items-baseline gap-2">
          <span className="tabular font-mono text-[17px] font-semibold text-ink">
            {readiness.score}
          </span>
          <Badge tone={band.tone}>{band.label}</Badge>
        </span>
      </div>
      <ul className="mt-2 space-y-1">
        {readiness.components.map((c) => (
          <li key={c.key} className="flex items-baseline justify-between gap-3">
            <span className={cn("text-xs", c.earned ? "text-muted" : "text-faint")}>
              {c.label}
              <span className="block text-2xs leading-snug text-faint">{c.detail}</span>
            </span>
            <span className={cn(
              "tabular shrink-0 font-mono text-xs",
              c.earned ? "text-success" : c.points ? "text-warning" : "text-faint"
            )}>
              {c.points}/{c.weight}
            </span>
          </li>
        ))}
        {readiness.penalty ? (
          <li className="flex items-baseline justify-between gap-3 border-t border-line pt-1">
            <span className="text-xs text-danger">
              Open risks
              <span className="block text-2xs leading-snug text-faint">
                {readiness.open_risks} open or mitigating risk(s) against this control.
              </span>
            </span>
            <span className="tabular shrink-0 font-mono text-xs text-danger">
              −{readiness.penalty}
            </span>
          </li>
        ) : null}
      </ul>
      {readiness.next_best_action ? (
        <p className="mt-2 border-t border-line pt-2 text-xs text-muted">
          <span className="text-faint">Next: </span>{readiness.next_best_action}
        </p>
      ) : null}
    </div>
  );
}
