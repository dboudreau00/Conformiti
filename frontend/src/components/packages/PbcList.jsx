/**
 * The auditor's request list ("prepared by client") for one package -- or,
 * with `mine`, every line assigned to the signed-in person across packages,
 * which is how a control owner with no package access answers what they were
 * asked for.
 *
 * Which buttons appear is decided by the server (`can` on each line), so the
 * screen never offers an action the API will refuse.
 */
import { useEffect, useState } from "react";
import { DownloadIcon, FileTextIcon, PaperclipIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../../api/client.js";
import { errorText } from "../../utils/a11y.js";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../ui/Panel.jsx";

const STATUS = {
  open: { label: "Open", tone: "warning" },
  provided: { label: "Provided", tone: "info" },
  accepted: { label: "Accepted", tone: "success" },
  returned: { label: "Returned", tone: "danger" },
  withdrawn: { label: "Withdrawn", tone: "muted" },
};
const EMPTY = { title: "", description: "", package_control: "", assignee: "", due_date: "", priority: "normal" };
const DATE = (iso) => (iso ? String(iso).slice(0, 10) : "");

export function PbcList({ pkg, mine = false, controls = [], canRaise = false, canAssemble = false, onOpen, onMessage }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [users, setUsers] = useState(null);
  const [docs, setDocs] = useState(null);
  const [attachTo, setAttachTo] = useState(null);
  const [attach, setAttach] = useState({ document: "", note: "" });
  const [editing, setEditing] = useState(null);
  const query = mine ? "/pbc-requests/?mine=1" : `/pbc-requests/?package=${pkg?.id}`;

  useEffect(() => {
    let live = true;
    setRows(null);
    fetchAll(query).then((r) => live && setRows(r)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [query]);

  useEffect(() => {
    if (canAssemble && (adding || editing) && users === null) {
      fetchAll("/users/").then((u) => setUsers(u.filter((x) => x.is_active))).catch(() => setUsers([]));
    }
  }, [canAssemble, adding, editing, users]);

  useEffect(() => {
    if (attachTo !== null && docs === null) {
      fetchAll("/documents/").then(setDocs).catch(() => setDocs([]));
    }
  }, [attachTo, docs]);

  const reload = async () => setRows(await fetchAll(query));

  async function act(key, fn, ok) {
    setBusy(key);
    try {
      await fn();
      await reload();
      if (ok) onMessage?.({ ok: true, text: ok });
    } catch (e) {
      onMessage?.({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const raise = (e) => {
    e.preventDefault();
    return act("raise", async () => {
      await api.post("/pbc-requests/", {
        package: pkg.id, title: form.title.trim(), description: form.description,
        package_control: form.package_control ? Number(form.package_control) : null,
        assignee: form.assignee ? Number(form.assignee) : null,
        due_date: form.due_date || null, priority: form.priority,
      });
      setForm(EMPTY);
      setAdding(false);
    }, "Request raised.");
  };

  const provide = (r) => {
    const hasItems = (r.items || []).length > 0;
    const note = window.prompt(hasItems
      ? "A note for the auditor (optional):"
      : "Nothing is attached. Say why, or cancel and attach a document first:", r.response_note || "");
    if (note === null || (!hasItems && !note.trim())) return undefined;
    return act(`provide-${r.id}`, () => api.post(`/pbc-requests/${r.id}/provide/`, { response_note: note }), `${r.reference} marked provided.`);
  };
  const accept = (r) => act(`accept-${r.id}`, () => api.post(`/pbc-requests/${r.id}/accept/`), `${r.reference} accepted.`);
  const giveBack = (r) => {
    const note = window.prompt("What is missing or wrong?");
    if (!note || !note.trim()) return undefined;
    return act(`return-${r.id}`, () => api.post(`/pbc-requests/${r.id}/return/`, { returned_note: note }), `${r.reference} returned.`);
  };
  const withdraw = (r) => {
    if (!window.confirm(`Withdraw ${r.reference}? The line stays on the list as withdrawn.`)) return undefined;
    return act(`withdraw-${r.id}`, () => api.post(`/pbc-requests/${r.id}/withdraw/`), `${r.reference} withdrawn.`);
  };
  const attachDoc = (e, r) => {
    e.preventDefault();
    return act(`attach-${r.id}`, async () => {
      await api.post("/pbc-items/", { request: r.id, document: Number(attach.document), note: attach.note });
      setAttach({ document: "", note: "" });
      setAttachTo(null);
    }, "Document attached.");
  };
  const detach = (r, item) => act(`detach-${item.id}`, () => api.delete(`/pbc-items/${item.id}/`));
  const saveEdit = (e, r) => {
    e.preventDefault();
    return act(`edit-${r.id}`, async () => {
      await api.patch(`/pbc-requests/${r.id}/`, {
        due_date: editing.due_date || null, assignee: editing.assignee ? Number(editing.assignee) : null,
        priority: editing.priority,
      });
      setEditing(null);
    }, "Request updated.");
  };
  const open = (r, item) => onOpen?.({
    title: item.document_name,
    subtitle: `${r.reference} · ${r.package_name}`,
    previewUrl: item.preview_url,
    downloadUrl: item.download_url,
    filename: item.document_name,
    facts: [
      { label: "Version when attached", value: `v${item.version}` },
      { label: "Digest at attachment (SHA-256)", value: item.content_sha256 || "—", mono: true },
      { label: "Attached by", value: `${item.attached_by_name} · ${DATE(item.attached_at)}` },
    ],
  });

  if (mine && rows !== null && rows.length === 0) return null;

  const summary = (rows || []).reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    if (r.is_overdue) acc.overdue += 1;
    return acc;
  }, { overdue: 0 });
  const title = mine ? "Auditor requests assigned to you" : "Request list";
  const id = (k) => `pbc-${k}`;

  return (
    <Panel className="overflow-hidden" aria-label={title} role="region">
      <PanelHeader title={title} meta={rows ? `${rows.length} line${rows.length === 1 ? "" : "s"}${summary.overdue ? ` · ${summary.overdue} overdue` : ""}` : ""}>
        <span className="flex items-center gap-2">
          {!mine && rows && rows.length ? (
            <Button size="sm" variant="ghost" onClick={() => downloadFile(`/pbc-requests/export/?package=${pkg.id}`, "pbc-requests.csv")}
                    icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
              CSV
            </Button>
          ) : null}
          {canRaise ? (
            <Button size="sm" variant={adding ? "secondary" : "primary"} aria-expanded={adding} onClick={() => setAdding((x) => !x)}>
              Add request
            </Button>
          ) : null}
        </span>
      </PanelHeader>

      {adding && canRaise ? (
        <form onSubmit={raise} className="grid gap-2.5 border-b border-line bg-surface-2 px-5 py-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor={id("title")} className="field-label">What is being asked for</label>
            <input id={id("title")} className="input" required value={form.title} placeholder="Termination tickets for the period"
                   onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor={id("description")} className="field-label">Detail (optional)</label>
            <textarea id={id("description")} className="input min-h-[60px]" value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <div>
            <label htmlFor={id("control")} className="field-label">Control</label>
            <select id={id("control")} className="input" value={form.package_control} onChange={(e) => setForm({ ...form, package_control: e.target.value })}>
              <option value="">Not tied to a control</option>
              {controls.map((c) => <option key={c.id} value={c.id}>{c.control_ref} — {c.title}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={id("due")} className="field-label">Due</label>
            <input id={id("due")} type="date" className="input" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
          </div>
          {canAssemble ? (
            <div>
              <label htmlFor={id("assignee")} className="field-label">Assign to</label>
              <select id={id("assignee")} className="input" value={form.assignee} onChange={(e) => setForm({ ...form, assignee: e.target.value })}>
                <option value="">Nobody yet</option>
                {(users || []).map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
              </select>
            </div>
          ) : null}
          <div>
            <label htmlFor={id("priority")} className="field-label">Priority</label>
            <select id={id("priority")} className="input" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
              <option value="normal">Normal</option>
              <option value="high">High</option>
            </select>
          </div>
          <div className="flex items-center gap-2 sm:col-span-2">
            <Button type="submit" size="sm" variant="primary" disabled={busy === "raise" || !form.title.trim()}>Raise</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </form>
      ) : null}

      {rows === null ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty title="Nothing requested yet">
          {canRaise
            ? "Raise the lines the auditor has asked for, assign each one, and answer it by attaching documents."
            : "The auditor's requests for this package will appear here."}
        </Empty>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((r) => {
            const s = STATUS[r.status] || STATUS.open;
            const can = r.can || {};
            return (
              <li key={r.id} className="px-5 py-3.5" data-reference={r.reference}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium text-ink">
                      <span className="font-mono text-xs text-muted">{r.reference}</span>{" "}
                      {r.title}
                      {r.priority === "high" ? <Badge tone="danger" mono className="ml-2">high</Badge> : null}
                    </span>
                    <Label className="block whitespace-normal">
                      {mine ? `${r.package_name} · ` : ""}
                      {r.control_ref ? `${r.control_ref} · ` : ""}
                      raised by {r.requested_by_name} ({r.requested_by_side})
                      {r.assignee_name ? ` · assigned to ${r.assignee_name}` : " · unassigned"}
                      {r.due_date ? ` · due ${r.due_date}` : ""}
                    </Label>
                    {r.description ? <span className="mt-1 block text-xs leading-snug text-muted">{r.description}</span> : null}
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    {r.is_overdue ? <Badge tone="danger" dot>Overdue</Badge> : null}
                    <Badge tone={s.tone} dot>{s.label}</Badge>
                  </span>
                </div>

                {r.status === "returned" && r.returned_note ? (
                  <p className="mt-2 text-xs leading-snug text-danger"><span className="text-faint">Returned: </span>{r.returned_note}</p>
                ) : null}
                {r.response_note ? (
                  <p className="mt-2 text-xs leading-snug text-muted"><span className="text-faint">Answer: </span>{r.response_note}</p>
                ) : null}
                {r.accepted_at ? <Label className="mt-1 block">Accepted by {r.accepted_by_name} · {DATE(r.accepted_at)}</Label> : null}

                {(r.items || []).length ? (
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {r.items.map((item) => (
                      <li key={item.id} className="flex items-center gap-1">
                        <button type="button" onClick={() => open(r, item)}
                                className="flex items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2 py-1 text-2xs text-muted transition-colors duration-150 ease-out hover:border-line-strong hover:text-ink"
                                title={`Open · v${item.version}${item.content_sha256 ? ` · ${item.content_sha256.slice(0, 16)}…` : ""}`}>
                          <FileTextIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
                          {item.document_name}
                        </button>
                        {can.attach ? (
                          <button type="button" className="link text-2xs" aria-label={`Detach ${item.document_name}`} disabled={busy === `detach-${item.id}`} onClick={() => detach(r, item)}>×</button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {attachTo === r.id ? (
                  <form onSubmit={(e) => attachDoc(e, r)} className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                    <div>
                      <label htmlFor={id(`doc-${r.id}`)} className="field-label">Document</label>
                      <select id={id(`doc-${r.id}`)} className="input input-sm" required value={attach.document} onChange={(e) => setAttach({ ...attach, document: e.target.value })}>
                        <option value="">{docs === null ? "Loading…" : "Choose a document you can see…"}</option>
                        {(docs || []).map((d) => <option key={d.id} value={d.id}>{d.name}{d.control_id ? ` (${d.control_id})` : ""}</option>)}
                      </select>
                    </div>
                    <div>
                      <label htmlFor={id(`note-${r.id}`)} className="field-label">Note (optional)</label>
                      <input id={id(`note-${r.id}`)} className="input input-sm" value={attach.note} onChange={(e) => setAttach({ ...attach, note: e.target.value })} />
                    </div>
                    <div className="flex items-end gap-1.5">
                      <Button type="submit" size="sm" variant="primary" disabled={!attach.document || busy === `attach-${r.id}`}>Attach</Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setAttachTo(null)}>Cancel</Button>
                    </div>
                  </form>
                ) : null}

                {editing && editing.id === r.id ? (
                  <form onSubmit={(e) => saveEdit(e, r)} className="mt-2 grid gap-2 sm:grid-cols-[160px_minmax(0,1fr)_120px_auto]">
                    <div>
                      <label htmlFor={id(`edit-due-${r.id}`)} className="field-label">Due</label>
                      <input id={id(`edit-due-${r.id}`)} type="date" className="input input-sm" value={editing.due_date} onChange={(e) => setEditing({ ...editing, due_date: e.target.value })} />
                    </div>
                    <div>
                      <label htmlFor={id(`edit-assignee-${r.id}`)} className="field-label">Assign to</label>
                      <select id={id(`edit-assignee-${r.id}`)} className="input input-sm" value={editing.assignee} onChange={(e) => setEditing({ ...editing, assignee: e.target.value })}>
                        <option value="">Nobody</option>
                        {(users || []).map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                      </select>
                    </div>
                    <div>
                      <label htmlFor={id(`edit-priority-${r.id}`)} className="field-label">Priority</label>
                      <select id={id(`edit-priority-${r.id}`)} className="input input-sm" value={editing.priority} onChange={(e) => setEditing({ ...editing, priority: e.target.value })}>
                        <option value="normal">Normal</option>
                        <option value="high">High</option>
                      </select>
                    </div>
                    <div className="flex items-end gap-1.5">
                      <Button type="submit" size="sm" variant="primary" disabled={busy === `edit-${r.id}`}>Save</Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                    </div>
                  </form>
                ) : null}

                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {can.attach && attachTo !== r.id ? (
                    <Button size="sm" variant="ghost" onClick={() => { setAttachTo(r.id); setAttach({ document: "", note: "" }); }}
                            icon={<PaperclipIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                      Attach document
                    </Button>
                  ) : null}
                  {can.answer ? <Button size="sm" variant="primary" disabled={busy === `provide-${r.id}`} onClick={() => provide(r)}>Mark provided</Button> : null}
                  {can.judge ? (
                    <>
                      <Button size="sm" variant="primary" disabled={busy === `accept-${r.id}`} onClick={() => accept(r)}>Accept</Button>
                      <Button size="sm" variant="danger" disabled={busy === `return-${r.id}`} onClick={() => giveBack(r)}>Return</Button>
                    </>
                  ) : null}
                  {can.edit && canAssemble && !(editing && editing.id === r.id) ? (
                    <Button size="sm" variant="ghost" onClick={() => setEditing({ id: r.id, due_date: r.due_date || "", assignee: r.assignee ? String(r.assignee) : "", priority: r.priority })}>Edit</Button>
                  ) : null}
                  {can.withdraw ? <Button size="sm" variant="ghost" disabled={busy === `withdraw-${r.id}`} onClick={() => withdraw(r)}>Withdraw</Button> : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {!mine ? (
        <p className="border-t border-line px-5 py-3 text-xs text-muted">
          The auditor raises what they need, or you transcribe their list; each line is assigned and chased until it is answered, and the auditor accepts or returns the answer. Documents attached here are read under the same grant as the package.
        </p>
      ) : null}
    </Panel>
  );
}
