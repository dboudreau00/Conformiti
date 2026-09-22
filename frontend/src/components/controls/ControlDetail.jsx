import { useEffect, useMemo, useState } from "react";
import { PaperclipIcon } from "lucide-react";
import api, { fetchAll } from "../../api/client.js";
import { errorText } from "../../utils/a11y.js";
import { cn } from "../../utils/cn.js";
import { CONTROL_STATUS, DOC_STATUS, READINESS_BAND } from "../../utils/tone.js";
import DocumentViewer from "../documents/DocumentViewer.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { Label, Loading } from "../ui/Panel.jsx";

const STATUS_KEYS = Object.keys(CONTROL_STATUS);

// /control-evidence/choices/ sends at most this many documents, the first by
// name, so a list that long may not hold the one being looked for.
const CHOICES_CAP = 500;

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
  // Ticked documents, kept whole: a search that no longer lists one still
  // attaches it, and still knows its name if the server skips it.
  const [selDocs, setSelDocs] = useState([]);
  const [docQuery, setDocQuery] = useState("");
  const [found, setFound] = useState(null); // server matches for docQuery, when the list is capped
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false); // attach / unlink in flight
  const [saving, setSaving] = useState(false); // status / owner PATCH in flight
  const [notice, setNotice] = useState(null); // { ok?, warn?, err?, skipped? }
  const [viewing, setViewing] = useState(null); // in-browser viewer props
  // The test interval is typed, so it needs a draft of its own: a controlled
  // input whose onChange does not set state is put back by React after every
  // keystroke, and the field refuses everything typed into it.
  const [interval, setIntervalDraft] = useState(control.test_interval_days ?? "");
  useEffect(() => {
    setIntervalDraft(control.test_interval_days ?? "");
  }, [control.id, control.test_interval_days]);

  const openLink = (l) => setViewing({
    title: l.document_name,
    subtitle: `${l.folder_path} · evidence for ${control.control_id}`,
    previewUrl: `/documents/${l.document}/preview/`,
    downloadUrl: `/documents/${l.document}/download/`,
    filename: l.document_name,
    badge: DOC_STATUS[l.document_status] || { label: l.document_status, tone: "muted" },
    facts: [
      { label: "Folder", value: l.folder_path },
      { label: "Linked by", value: l.linked_by_name || "-" },
      { label: "Note", value: l.note || "-" },
    ],
  });

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
  const capped = (docChoices || []).length >= CHOICES_CAP;
  const available = useMemo(
    () => (docChoices || []).filter((d) => !linkedIds.has(d.id)),
    [docChoices, linkedIds]
  );

  // Filtering a capped list in the browser answered "No documents match." for
  // a document that sorts after the cap. When the list is capped, a search
  // also asks the server, which matches the name across every document the
  // caller can see, and its matches join the list.
  useEffect(() => {
    const term = docQuery.trim();
    if (!capped || !term) {
      setFound(null);
      setSearching(false);
      setSearchError("");
      return undefined;
    }
    let alive = true;
    setSearching(true);
    setSearchError("");
    const timer = setTimeout(() => {
      api.get("/control-evidence/choices/", { params: { q: term } })
        .then(({ data }) => { if (alive) setFound(data.documents || []); })
        .catch((e) => { if (alive) setSearchError(errorText(e, "Couldn't search every document. Change the search to try again.")); })
        .finally(() => { if (alive) setSearching(false); });
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [docQuery, capped]);

  const visibleDocs = useMemo(() => {
    const q = docQuery.trim().toLowerCase();
    if (!q) return available;
    // The server's matches for an earlier query can still be here while the
    // next one is in flight, so the merged list goes through the same filter.
    const listed = new Set(available.map((d) => d.id));
    const more = (found || []).filter((d) => !listed.has(d.id) && !linkedIds.has(d.id));
    return available.concat(more).filter((d) => `${d.name} ${d.path}`.toLowerCase().includes(q));
  }, [available, found, linkedIds, docQuery]);
  const picked = (docId) => selDocs.some((d) => d.id === docId);
  const hiddenPicks = selDocs.filter((s) => !visibleDocs.some((d) => d.id === s.id)).length;
  function toggleDoc(doc) {
    setSelDocs((sel) => (sel.some((d) => d.id === doc.id) ? sel.filter((d) => d.id !== doc.id) : [...sel, doc]));
  }

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
    const chosen = selDocs;
    const docName = (docId) => chosen.find((d) => d.id === docId)?.name || `Document #${docId}`;
    setBusy(true);
    setNotice(null);
    try {
      const { data } = await api.post("/control-evidence/bulk/", {
        control: id,
        documents: chosen.map((d) => Number(d.id)),
        note,
      });
      const created = data.created || [];
      const skipped = data.skipped || [];
      if (created.length) onEvidenceDelta(id, created.length);
      setSelDocs([]);
      setDocQuery("");
      setNote("");
      // Re-read the list so each new link carries its server-computed
      // can_unlink flag (the bulk response is serialized without it).
      await loadLinks();
      setNotice({
        ok: `${created.length} attached`,
        skipped: skipped.map((s) => `${docName(s.document)}: ${s.reason}`),
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
          <p className="text-[13px] leading-relaxed text-ink">{control.objective || "-"}</p>
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

        {/* Testing is 15 points of the readiness score and, until 0.9.5, had
            no way to be recorded except the API: the toast copy for these
            two fields existed, the inputs did not. */}
        <div className="rounded-xl border border-line bg-surface p-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              {canManage ? (
                <>
                  <label htmlFor={`control-tested-${id}`} className="field-label">Last tested</label>
                  <input
                    id={`control-tested-${id}`}
                    type="date"
                    className="input input-sm"
                    value={control.last_tested_on || ""}
                    max={new Date().toISOString().slice(0, 10)}
                    disabled={saving}
                    onChange={(e) => patch("last_tested_on", e.target.value || null)}
                  />
                </>
              ) : (
                <>
                  <Label className="mb-1.5 block">Last tested</Label>
                  <p className={cn("text-[13px]", control.last_tested_on ? "text-ink" : "text-danger")}>
                    {control.last_tested_on || "Never"}
                  </p>
                </>
              )}
            </div>
            <div>
              {canManage ? (
                <>
                  <label htmlFor={`control-interval-${id}`} className="field-label">Test every (days)</label>
                  <input
                    id={`control-interval-${id}`}
                    type="number"
                    min={1}
                    max={3650}
                    className="input input-sm"
                    value={interval}
                    placeholder="365"
                    disabled={saving}
                    onBlur={() => {
                      const raw = String(interval).trim();
                      const next = raw === "" ? null : Number(raw);
                      if (next !== null && (!Number.isFinite(next) || next < 1 || next > 3650)) {
                        setIntervalDraft(control.test_interval_days ?? "");
                        setNotice({ err: "A test interval is between 1 and 3650 days." });
                        return;
                      }
                      if (next !== (control.test_interval_days ?? null)) patch("test_interval_days", next);
                    }}
                    onChange={(e) => setIntervalDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                  />
                </>
              ) : (
                <>
                  <Label className="mb-1.5 block">Test every</Label>
                  <p className="text-[13px] text-ink">{control.test_interval_days ? `${control.test_interval_days} days` : "Default"}</p>
                </>
              )}
            </div>
          </div>
          <p className="mt-2 text-2xs text-faint">
            {control.last_tested_by_name
              ? `Recorded by ${control.last_tested_by_name}${control.last_tested_recorded_at ? ` on ${String(control.last_tested_recorded_at).slice(0, 10)}` : ""}.`
              : "Recording a test date stamps who recorded it and when, and writes to the audit trail."}
          </p>
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
                        <button type="button" onClick={() => openLink(l)} title="Open in browser"
                                className="truncate text-left text-[13px] font-medium text-ink transition-colors duration-150 ease-out hover:text-accent">
                          {l.document_name}
                        </button>
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
            {/* A failed load leaves docChoices null. That is reported on its
                own, not above a claim that every document is already linked,
                and an error left over from before a retry filled the list is
                stale, so it only shows while there is no list. */}
            {!docChoices ? (
              choicesError ? (
                <div className="notice notice-err" role="alert">{choicesError}</div>
              ) : (
                <Loading className="py-3">Loading documents…</Loading>
              )
            ) : (
              <>
                <label htmlFor={`attach-docs-${id}`} className="field-label">Documents</label>
                {available.length === 0 && !capped ? (
                  <p className="text-xs text-muted">Every document you can see is already linked to this control.</p>
                ) : (
                  <>
                    {/* The box sits inside the attach form, and Enter in a
                        search box means search, not attach what is ticked. */}
                    <input
                      id={`attach-docs-${id}`}
                      className="input input-sm"
                      placeholder="Find a document"
                      value={docQuery}
                      onChange={(e) => setDocQuery(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
                    />
                    <div className="mt-2 max-h-[200px] overflow-y-auto rounded-lg border border-line">
                      {visibleDocs.length === 0 ? (
                        <p className="px-3 py-3 text-xs text-muted">
                          {searching
                            ? "Searching every document…"
                            : searchError
                              ? `No matches in the first ${CHOICES_CAP} documents.`
                              : "No documents match."}
                        </p>
                      ) : (
                        <ul className="divide-y divide-line">
                          {visibleDocs.map((d) => (
                            <li key={d.id}>
                              <label className="flex cursor-pointer items-start gap-2 px-3 py-1.5 hover:bg-surface-2">
                                <input
                                  type="checkbox"
                                  className="mt-1"
                                  checked={picked(d.id)}
                                  onChange={() => toggleDoc(d)}
                                  aria-label={`Attach ${d.name}`}
                                />
                                <span className="min-w-0">
                                  <span className="block truncate text-[13px] text-ink">{d.name}</span>
                                  <Label className="block truncate">{d.path}</Label>
                                </span>
                              </label>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    {searchError ? (
                      <p className="mt-1.5 text-2xs text-danger" role="alert">{searchError}</p>
                    ) : capped && !docQuery.trim() ? (
                      <p className="mt-1.5 text-2xs text-faint">
                        Showing the first {CHOICES_CAP} documents by name. Search to find the others.
                      </p>
                    ) : null}
                    {hiddenPicks ? (
                      <p className="mt-1.5 text-2xs text-faint">
                        {hiddenPicks} ticked {hiddenPicks === 1 ? "document is" : "documents are"} not in the list above and will be attached too.
                      </p>
                    ) : null}
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
      <DocumentViewer open={!!viewing} {...(viewing || {})} onClose={() => setViewing(null)} />
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
