/**
 * The RACI matrix: who is Responsible, Accountable, Consulted and Informed
 * for each control, people and vendors alike. A control's owner is shown as
 * its implicit Accountable, and a vendor that states it does (or shares) a
 * control on its shared responsibility matrix shows as implicitly
 * Responsible, so the grid reflects the register as it stands rather than
 * only what has been typed here.
 */
import { useEffect, useMemo, useState } from "react";
import { DownloadIcon, XIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { PanelTransition } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { useConfirm } from "../components/ui/Dialog.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Chip, SegmentedControl } from "../components/ui/SegmentedControl.jsx";
import { ControlPicker } from "../components/controls/ControlPicker.jsx";
import { usePage } from "../components/ui/ShowMore.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";
import { TONE_RING, TONE_TEXT, TONE_WASH } from "../utils/tone.js";

const ROLES = [
  ["responsible", "Responsible", "Does the work"],
  ["accountable", "Accountable", "Answers for it: exactly one"],
  ["consulted", "Consulted", "Asked before decisions"],
  ["informed", "Informed", "Told afterwards"],
];
const PARTY = [{ id: "user", label: "Person" }, { id: "vendor", label: "Vendor" }];
const EMPTY = { control: "", kind: "user", party: "", role: "responsible", note: "" };

// `role` is the column's label: one chip is one assignment, and a party can
// hold several roles on the same control, so its X names the role it removes.
function PartyChip({ x, role, canManage, onRemove }) {
  const tone = x.kind === "vendor" ? "info" : "accent";
  const title = [x.kind === "vendor" ? "Vendor" : "Person", x.note].filter(Boolean).join(" · ");
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full py-0.5 pl-2 text-2xs font-medium ring-1",
        x.implicit ? "border border-dashed border-line-strong bg-transparent pr-2 text-muted ring-0" : cn(TONE_WASH[tone], TONE_TEXT[tone], TONE_RING[tone]),
        !x.implicit && (canManage && x.id ? "pr-1" : "pr-2")
      )}
    >
      <span className="truncate">{x.name}</span>
      {x.kind === "vendor" ? <span className="text-[9px] uppercase tracking-label opacity-70">vendor</span> : null}
      {!x.implicit && canManage && x.id ? (
        <button type="button" aria-label={`Remove ${x.name} as ${role}`} onClick={() => onRemove(x)}
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full opacity-70 transition-opacity hover:opacity-100">
          <XIcon className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" />
        </button>
      ) : null}
    </span>
  );
}

export default function Responsibilities({ me }) {
  const canManage = !!(me?.is_superuser || me?.capabilities?.manage_frameworks);
  const { ask, confirmDialog } = useConfirm();
  const [data, setData] = useState(null);
  const [loadErr, setLoadErr] = useState(false);
  const [fw, setFw] = useState("");
  const [q, setQ] = useState("");
  const [gapsOnly, setGapsOnly] = useState(false);
  const [controls, setControls] = useState([]);
  const [users, setUsers] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState(EMPTY);

  async function load(framework = fw) {
    setLoadErr(false);
    try {
      const { data: d } = await api.get(`/responsibilities/matrix/${framework ? `?framework=${encodeURIComponent(framework)}` : ""}`);
      setData(d);
    } catch {
      setData(null);
      setLoadErr(true);
    }
  }
  useEffect(() => { load(fw); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [fw]);
  useEffect(() => {
    api.get("/control-evidence/choices/").then((r) => setControls(r.data.controls || [])).catch(() => setControls([]));
    fetchAll("/vendors/").then(setVendors).catch(() => setVendors([]));
    if (canManage) fetchAll("/users/").then((u) => setUsers(u.filter((x) => x.is_active))).catch(() => setUsers([]));
  }, [canManage]);

  const frameworks = useMemo(() => {
    const seen = new Map();
    for (const c of controls) if (!seen.has(c.framework)) seen.set(c.framework, c.framework_name);
    return Array.from(seen.entries());
  }, [controls]);
  // The real names, from the choices the page already loads: a hard-coded
  // map of three keys showed the other twenty-two frameworks as slugs.
  const names = useMemo(() => Object.fromEntries(frameworks), [frameworks]);
  const rows = useMemo(() => (data?.rows || []).filter((r) =>
    (!q || `${r.control_id} ${r.title}`.toLowerCase().includes(q.toLowerCase()))
    && (!gapsOnly || r.accountable.length === 0 || r.responsible.length === 0)
  ), [data, q, gapsOnly]);
  const page = usePage(rows, 100, [fw, q, gapsOnly]);
  const chosen = useMemo(() => controls.find((c) => String(c.id) === String(form.control)) || null, [controls, form.control]);
  const shared = (data?.rows || []).filter((r) => r.shared).length;
  const parties = form.kind === "vendor" ? vendors.map((v) => ({ id: v.id, name: v.name })) : users.map((u) => ({ id: u.id, name: u.full_name || u.username }));

  async function act(fn, okText) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      await load();
      if (okText) setMsg({ ok: true, text: okText });
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }
  // For a confirm dialog: it closes when onConfirm resolves, and `act`
  // resolves on a failure too, so a refused removal closed as if it had
  // worked. This throws the failure on, and the dialog shows it in place.
  async function actOrThrow(fn, okText) {
    let failed = null;
    await act(async () => {
      try { await fn(); } catch (e) { failed = e; throw e; }
    }, okText);
    if (failed) throw new Error(errorText(failed));
  }

  return (
    <PanelTransition>
      {confirmDialog}
      {msg ? (
        <div className={cn("notice mb-4 flex items-start justify-between gap-3", msg.ok ? "notice-ok" : "notice-err")} role={msg.ok ? "status" : "alert"}>
          <span>{msg.text}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setMsg(null)} className="shrink-0 opacity-70 hover:opacity-100"><XIcon className="h-3.5 w-3.5" /></button>
        </div>
      ) : null}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Controls" value={data ? data.count : "-"} detail={fw ? names[fw] || fw : "All frameworks"} />
        <StatCard label="No Accountable" value={data ? data.gaps.no_accountable : "-"} tone={data?.gaps.no_accountable ? "danger" : "success"} detail="Nobody answers for the control" />
        <StatCard label="No Responsible" value={data ? data.gaps.no_responsible : "-"} tone={data?.gaps.no_responsible ? "warning" : "success"} detail="Nobody does the work" />
        <StatCard label="Shared with a vendor" value={data ? shared : "-"} tone="info" detail="From vendors' responsibility matrices" />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Panel className="overflow-hidden">
          <PanelHeader title="Responsibility matrix" meta={data ? `Showing ${page.shown.toLocaleString()} of ${rows.length.toLocaleString()}` : "-"}>
            <Button size="sm" variant="ghost" icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                    onClick={() => downloadFile(`/responsibilities/export/${fw ? `?framework=${encodeURIComponent(fw)}` : ""}`, "responsibility-matrix.csv")}>
              Export
            </Button>
          </PanelHeader>
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-5 py-2.5">
            <label htmlFor="raci-framework" className="sr-only">Framework</label>
            <select id="raci-framework" className="input input-sm w-auto min-w-[220px]" value={fw}
                    onChange={(e) => setFw(e.target.value)}>
              <option value="">All frameworks</option>
              {frameworks.map(([k, name]) => <option key={k} value={k}>{name}</option>)}
            </select>
            <Chip active={gapsOnly} tone="danger" onClick={() => setGapsOnly((x) => !x)}>Gaps only</Chip>
            <label htmlFor="raci-search" className="sr-only">Search controls</label>
            <input id="raci-search" className="input input-sm ml-auto w-56" placeholder="Search controls…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {loadErr ? (
            <LoadError what="The responsibility matrix" onRetry={() => load(fw)} />
          ) : !data ? <Loading /> : rows.length === 0 ? (
            fw || q || gapsOnly ? (
              <Empty title="No controls match"
                     action={<Button size="sm" onClick={() => { setFw(""); setQ(""); setGapsOnly(false); }}>Clear filters</Button>}>
                Clear the filters to see the whole matrix.
              </Empty>
            ) : (
              <Empty title="No controls yet">
                Install a compliance pack, or load the framework library, and every control gets a row here.
              </Empty>
            )
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-xs">
                <thead className="bg-surface-2">
                  <tr>
                    <th className="px-4 py-2 text-left font-normal text-faint" scope="col">Control</th>
                    {ROLES.map(([k, l, hint]) => (
                      <th key={k} className="px-2 py-2 text-left font-normal text-faint" scope="col" title={hint}>{l}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {page.visible.map((r) => (
                    <tr key={r.control} className="align-top transition-colors duration-150 hover:bg-surface-2">
                      <td className="w-[300px] px-4 py-2">
                        <span className="block font-mono text-[11px] text-muted">{names[r.framework] || r.framework_name || r.framework} · {r.control_id}</span>
                        <span className="block text-[13px] text-ink">{r.title}</span>
                        {r.shared ? <Badge tone="info" mono className="mt-1">shared with vendor</Badge> : null}
                      </td>
                      {ROLES.map(([k, l]) => (
                        <td key={k} className="px-2 py-2">
                          {r[k].length === 0 ? (
                            <span className={cn("text-2xs", k === "accountable" ? "text-danger" : k === "responsible" ? "text-warning" : "text-faint")}>
                              {k === "accountable" ? "nobody" : "-"}
                            </span>
                          ) : (
                            <span className="flex flex-wrap gap-1">
                              {r[k].map((x, i) => (
                                <PartyChip key={x.id || `implicit-${x.kind}-${x.party_id}-${i}`} x={x} role={l} canManage={canManage}
                                           onRemove={(p) => ask({
                                             title: `Remove ${p.name} as ${l}?`,
                                             description: `Only this ${l} entry goes. Any other role ${p.name} holds on this control stays, and so do implied entries from ownership or a vendor matrix.`,
                                             confirmLabel: "Remove",
                                             onConfirm: () => actOrThrow(() => api.delete(`/responsibilities/${p.id}/`), `${p.name} removed as ${l}.`),
                                           })} />
                              ))}
                            </span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {page.remaining ? (
                <div className="border-t border-line px-5 py-3 text-center">
                  <Button size="sm" variant="secondary" onClick={page.more}>
                    Show {Math.min(page.size, page.remaining)} more of {page.remaining.toLocaleString()}
                  </Button>
                </div>
              ) : null}
            </div>
          )}
          <p className="border-t border-line px-5 py-3 text-xs text-muted">
            Dashed entries are implied: the control's owner as Accountable, and any vendor whose shared
            responsibility matrix claims the control as Responsible. Everything else was assigned here.
          </p>
        </Panel>

        <div className="space-y-4">
          {canManage ? (
            <Panel className="p-4">
              <Label className="mb-3 block">Assign a responsibility</Label>
              <form className="space-y-3" onSubmit={async (e) => {
                e.preventDefault();
                const body = { control: Number(form.control), role: form.role, note: form.note };
                body[form.kind === "vendor" ? "vendor" : "user"] = Number(form.party);
                if (await act(() => api.post("/responsibilities/", body), "Assigned.")) setForm((f) => ({ ...f, party: "", note: "" }));
              }}>
                <div>
                  <span className="field-label">Control</span>
                  {chosen ? (
                    <div className="mt-1 flex items-baseline gap-2 rounded-lg border border-line bg-surface-2 px-3 py-1.5">
                      <span className="shrink-0 font-mono text-xs text-accent">{chosen.label}</span>
                      <span className="truncate text-xs text-ink">{chosen.title}</span>
                      <button type="button" className="ml-auto shrink-0 text-2xs text-muted underline underline-offset-4 hover:text-ink"
                              onClick={() => setForm((f) => ({ ...f, control: "" }))}>
                        Change
                      </button>
                    </div>
                  ) : (
                    <ControlPicker
                      id="raci-control"
                      label="Control"
                      className="mt-1"
                      controls={controls.length ? controls : null}
                      framework={fw}
                      onPick={(c) => setForm((f) => ({ ...f, control: String(c.id) }))}
                    />
                  )}
                </div>
                <div>
                  <Label className="mb-1.5 block">Party</Label>
                  <SegmentedControl options={PARTY} value={form.kind} onChange={(kind) => setForm((f) => ({ ...f, kind, party: "" }))} layoutId="raci-party" ariaLabel="Party kind" />
                </div>
                <div>
                  <label htmlFor="raci-party" className="field-label">{form.kind === "vendor" ? "Vendor" : "Person"}</label>
                  <select id="raci-party" className="input input-sm" required value={form.party} onChange={(e) => setForm((f) => ({ ...f, party: e.target.value }))}>
                    <option value="">{form.kind === "vendor" ? "Choose a vendor…" : "Choose a person…"}</option>
                    {parties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="raci-role" className="field-label">Role</label>
                  <select id="raci-role" className="input input-sm" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
                    {ROLES.map(([k, l, hint]) => <option key={k} value={k}>{l}, {hint}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="raci-note" className="field-label">Note (optional)</label>
                  <input id="raci-note" className="input input-sm" maxLength={255} value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} placeholder="Why this party" />
                </div>
                <Button type="submit" size="sm" variant="primary" className="w-full" disabled={busy || !form.control || !form.party}>
                  {busy ? "Saving…" : "Assign"}
                </Button>
              </form>
            </Panel>
          ) : null}
          <Panel className="p-4">
            <Label className="mb-2 block">Reading the matrix</Label>
            <ul className="space-y-2 text-xs text-muted">
              {ROLES.map(([k, l, hint]) => (
                <li key={k} className="flex gap-2">
                  <span className="w-24 shrink-0 font-medium text-ink">{l}</span>
                  <span>{hint}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted">
              A control with no Accountable party has nobody to answer for it at audit; the API refuses a second one so the
              matrix cannot drift into "everyone and no one".
            </p>
          </Panel>
        </div>
      </div>
    </PanelTransition>
  );
}
