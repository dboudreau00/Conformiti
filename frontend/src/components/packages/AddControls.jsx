/**
 * Put controls into a draft package from the page, not from curl.
 *
 * Until 0.9.5 the only caller of POST add_controls was the test suite, and
 * the empty state told the person to "POST their ids". Year-two fieldwork
 * therefore started in a terminal. This is the picker: every control in
 * the workspace, filtered by framework and text, chosen with checkboxes,
 * added in one request with the evidence already linked to each one pinned
 * — and a plain report of which evidence was skipped because the person
 * assembling the package cannot see it, which the API has always returned
 * and nothing displayed.
 */
import { useEffect, useMemo, useState } from "react";
import { PlusIcon, SearchIcon } from "lucide-react";
import api, { fetchAll } from "../../api/client.js";
import { errorText } from "../../utils/a11y.js";
import { CONTROL_STATUS } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { Label, Loading, Panel, PanelHeader } from "../ui/Panel.jsx";

export function AddControls({ packageId, inScope, onAdded, onError }) {
  const [frameworks, setFrameworks] = useState(null);
  const [framework, setFramework] = useState("all");
  const [controls, setControls] = useState(null);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState(() => new Set());
  const [withEvidence, setWithEvidence] = useState(true);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open || frameworks) return;
    fetchAll("/frameworks/").then(setFrameworks).catch((e) => {
      setFrameworks([]);
      onError?.(errorText(e, "Couldn't load frameworks."));
    });
  }, [open, frameworks, onError]);

  useEffect(() => {
    if (!open || !frameworks) return;
    let alive = true;
    setControls(null);
    const keys = framework === "all" ? frameworks.map((f) => f.key) : [framework];
    Promise.all(keys.map((k) => api.get(`/frameworks/${k}/controls/`)))
      .then((rs) => { if (alive) setControls(rs.flatMap((r) => r.data.results || r.data)); })
      .catch((e) => {
        if (!alive) return;
        setControls([]);
        onError?.(errorText(e, "Couldn't load controls."));
      });
    return () => { alive = false; };
  }, [open, framework, frameworks, onError]);

  const inScopeIds = useMemo(() => new Set((inScope || []).map((r) => r.control)), [inScope]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (controls || []).filter((c) =>
      !inScopeIds.has(c.id)
      && (!q || `${c.control_id} ${c.title} ${c.category_name || ""}`.toLowerCase().includes(q)));
  }, [controls, query, inScopeIds]);

  function toggle(id) {
    setChosen((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function add() {
    if (!chosen.size) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/evidence-packages/${packageId}/add_controls/`, {
        controls: Array.from(chosen), with_evidence: withEvidence,
      });
      setChosen(new Set());
      await onAdded?.(data);
    } catch (e) {
      onError?.(errorText(e, "The controls could not be added."));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Panel className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <PanelHeader title="Scope" meta={`${inScopeIds.size} in scope`} />
            <p className="mt-1 text-xs text-muted">Choose the controls this audit covers. Evidence already linked to each one is pinned as it is today.</p>
          </div>
          <Button size="sm" variant="primary" onClick={() => setOpen(true)}
                  icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
            Add controls
          </Button>
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="p-5" aria-label="Add controls to the package">
      <PanelHeader title="Add controls" meta={`${inScopeIds.size} already in scope`}>
        <Button size="sm" variant="ghost" onClick={() => { setOpen(false); setChosen(new Set()); }}>Done</Button>
      </PanelHeader>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="min-w-[180px]">
          <label htmlFor={`add-fw-${packageId}`} className="field-label">Framework</label>
          <select id={`add-fw-${packageId}`} className="input input-sm" value={framework}
                  onChange={(e) => setFramework(e.target.value)} disabled={!frameworks}>
            <option value="all">All frameworks</option>
            {(frameworks || []).map((f) => <option key={f.key} value={f.key}>{f.name}</option>)}
          </select>
        </div>
        <div className="min-w-[220px] flex-1">
          <label htmlFor={`add-q-${packageId}`} className="field-label">Find</label>
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" strokeWidth={2} aria-hidden="true" />
            <input id={`add-q-${packageId}`} className="input input-sm pl-8" value={query} placeholder="Control id, title or category"
                   onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        <label className="flex items-center gap-2 pb-2 text-xs text-muted">
          <input type="checkbox" checked={withEvidence} onChange={(e) => setWithEvidence(e.target.checked)} />
          Pin linked evidence
        </label>
      </div>

      <div className="mt-3 max-h-[360px] overflow-y-auto rounded-lg border border-line">
        {controls === null ? (
          <Loading className="py-6">Loading controls…</Loading>
        ) : visible.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-muted">
            {controls.length && inScopeIds.size ? "Every matching control is already in scope." : "No controls match."}
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {visible.map((c) => {
              const status = CONTROL_STATUS[c.status] || { label: c.status, tone: "muted" };
              const checked = chosen.has(c.id);
              return (
                <li key={c.id}>
                  <label className="flex cursor-pointer items-start gap-3 px-3 py-2 hover:bg-surface-2">
                    <input type="checkbox" className="mt-1" checked={checked} onChange={() => toggle(c.id)}
                           aria-label={`Add ${c.control_id} ${c.title}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] text-ink">
                        <span className="font-mono text-xs text-muted">{c.control_id}</span> {c.title}
                      </span>
                      <Label className="block">
                        {c.framework}{c.category_name ? ` · ${c.category_name}` : ""}
                        {typeof c.evidence_count === "number" ? ` · ${c.evidence_count} evidence` : ""}
                      </Label>
                    </span>
                    <Badge tone={status.tone} dot>{status.label}</Badge>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted">
          {chosen.size ? `${chosen.size} selected` : "Tick the controls to include."}
          {visible.length && chosen.size !== visible.length ? (
            <button type="button" className="link ml-2" onClick={() => setChosen(new Set(visible.map((c) => c.id)))}>
              Select all {visible.length} shown
            </button>
          ) : null}
          {chosen.size ? (
            <button type="button" className="link ml-2" onClick={() => setChosen(new Set())}>Clear</button>
          ) : null}
        </span>
        <Button size="sm" variant="primary" disabled={busy || !chosen.size} onClick={add}
                icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
          {busy ? "Adding…" : `Add ${chosen.size || ""} ${chosen.size === 1 ? "control" : "controls"}`.replace("  ", " ")}
        </Button>
      </div>
    </Panel>
  );
}
