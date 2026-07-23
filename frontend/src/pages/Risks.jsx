import { useEffect, useRef, useState } from "react";
import api from "../api/client.js";

const STATUS = [
  ["open", "Open", "overdue"],
  ["mitigating", "Mitigating", "soon"],
  ["accepted", "Accepted", "neutral"],
  ["closed", "Closed", "ok"],
];
const TYPES = [
  ["control_gap", "Control gap"], ["audit_finding", "Audit finding"],
  ["pentest", "Pen test"], ["vendor", "Vendor"],
  ["incident", "Incident"], ["other", "Other"],
];
const TREATMENTS = [
  ["mitigate", "Mitigate"], ["accept", "Accept"],
  ["transfer", "Transfer"], ["avoid", "Avoid"],
];
const RATING_CLS = { low: "neutral", moderate: "soon", high: "high", critical: "overdue" };
const SCALE = [1, 2, 3, 4, 5];

const TEMPLATE_CSV =
  "Title,Description,Status,Type,Likelihood,Impact,Owner,Control,Due date,Jira,Mitigation plan,Note\n" +
  "Example: laptops missing encryption,12 laptops without disk encryption,Open,Control gap,High,High,owen,CC6.1,2026-09-15,SEC-101,Enforce via MDM,First note\n";

function statusBadge(s) {
  const m = STATUS.find((x) => x[0] === s);
  return <span className={`badge ${m?.[2] || "neutral"}`}><span className="dot" />{m?.[1] || s}</span>;
}

export default function Risks({ me }) {
  const [risks, setRisks] = useState([]);
  const [summary, setSummary] = useState(null);
  const [filter, setFilter] = useState("live");
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState([]);
  const [controls, setControls] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [sel, setSel] = useState(null);          // selected risk object
  const [notes, setNotes] = useState([]);
  const [noteText, setNoteText] = useState("");
  const [planDraft, setPlanDraft] = useState("");
  const fileRef = useRef(null);

  const canManage = me?.capabilities?.manage_frameworks;
  const canEditRisk = (r) => canManage || (r.owner && r.owner === me?.id);

  async function loadRisks() {
    setLoading(true);
    let page = 1, all = [];
    for (;;) {
      const r = await api.get(`/risks/?page=${page}`);
      const data = r.data.results || r.data;
      all = all.concat(data);
      if (!r.data.next || page >= 5) break;
      page += 1;
    }
    setRisks(all);
    setLoading(false);
  }

  function loadSummary() {
    api.get("/risks/summary/").then((r) => setSummary(r.data));
  }

  useEffect(() => {
    loadRisks();
    loadSummary();
    api.get("/users/").then((r) => setUsers(r.data.results || r.data)).catch(() => {});
    api.get("/control-evidence/choices/").then((r) => setControls(r.data.controls)).catch(() => {});
  }, []);

  function applyUpdate(updated) {
    setRisks((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
    if (sel?.id === updated.id) setSel(updated);
    loadSummary();
  }

  async function patch(risk, payload) {
    const { data } = await api.patch(`/risks/${risk.id}/`, payload);
    applyUpdate(data);
  }

  async function openRisk(r) {
    if (sel?.id === r.id) { setSel(null); return; }
    setSel(r);
    setPlanDraft(r.mitigation_plan || "");
    setNoteText("");
    const res = await api.get(`/risk-notes/?risk=${r.id}`);
    setNotes(res.data.results || res.data);
  }

  async function addNote(e) {
    e.preventDefault();
    if (!noteText.trim()) return;
    const { data } = await api.post("/risk-notes/", { risk: sel.id, text: noteText.trim() });
    setNotes((ns) => [...ns, data]);
    setNoteText("");
    setRisks((rs) => rs.map((r) => (r.id === sel.id ? { ...r, note_count: (r.note_count || 0) + 1 } : r)));
  }

  async function createRisk(e) {
    e.preventDefault();
    const f = e.target;
    const payload = {
      title: f.title.value.trim(),
      risk_type: f.rtype.value,
      likelihood: Number(f.likelihood.value),
      impact: Number(f.impact.value),
      owner: f.owner.value || null,
      control: f.control.value || null,
      due_date: f.due.value || null,
      description: f.description.value,
      mitigation_plan: f.plan.value,
    };
    if (!payload.title) return;
    const { data } = await api.post("/risks/", payload);
    setRisks((rs) => [data, ...rs]);
    loadSummary();
    setShowNew(false);
    f.reset();
  }

  async function doImport(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const { data } = await api.post("/risks/import/", fd);
      setImportResult(data);
      loadRisks();
      loadSummary();
    } catch (err) {
      const detail = err.response?.data?.file || err.response?.data?.detail || "Import failed.";
      setImportResult({ error: Array.isArray(detail) ? detail.join(" ") : String(detail) });
    }
  }

  function download(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  }

  async function exportCsv() {
    const r = await api.get("/risks/export/", { responseType: "blob" });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url; a.download = "risk-register.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  const shown = risks.filter((r) =>
    filter === "all" ? true :
    filter === "live" ? (r.status === "open" || r.status === "mitigating") :
    r.status === filter
  );

  return (
    <>
      <div className="pagehead">
        <div>
          {summary && (
            <div className="chips">
              <div className={"chip" + (filter === "live" ? " active" : "")} onClick={() => setFilter("live")}>
                {summary.open + summary.mitigating} live
              </div>
              <div className="chip" style={{ cursor: "default", color: summary.overdue ? "var(--red)" : undefined }}>
                {summary.overdue} overdue
              </div>
              <div className="chip" style={{ cursor: "default" }}>
                {summary.by_rating.critical + summary.by_rating.high} high / critical
              </div>
              <div className={"chip" + (filter === "closed" ? " active" : "")} onClick={() => setFilter("closed")}>
                {summary.closed} closed
              </div>
              <div className={"chip" + (filter === "all" ? " active" : "")} onClick={() => setFilter("all")}>
                all
              </div>
            </div>
          )}
        </div>
        <div className="toolbar">
          <button className="btn small" onClick={() => download("risk-import-template.csv", TEMPLATE_CSV)}>Template</button>
          {canManage && (
            <>
              <input ref={fileRef} type="file" accept=".csv,.xlsx" style={{ display: "none" }} onChange={doImport} />
              <button className="btn small" onClick={() => fileRef.current.click()}>Import CSV/XLSX</button>
            </>
          )}
          <button className="btn small" onClick={exportCsv}>Export</button>
          {canManage && (
            <button className="btn primary small" onClick={() => setShowNew((v) => !v)}>
              {showNew ? "Cancel" : "New risk"}
            </button>
          )}
        </div>
      </div>

      {importResult && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-head">
            <h2>Import result</h2>
            <button className="btn small" onClick={() => setImportResult(null)}>Dismiss</button>
          </div>
          <div className="card-body" style={{ fontSize: 13.5 }}>
            {importResult.error ? (
              <span style={{ color: "var(--red)" }}>{importResult.error}</span>
            ) : (
              <>
                <div><b>{importResult.created}</b> risk{importResult.created === 1 ? "" : "s"} created
                  {importResult.skipped.length > 0 && <> · {importResult.skipped.length} skipped</>}
                  {importResult.warnings.length > 0 && <> · {importResult.warnings.length} warning{importResult.warnings.length === 1 ? "" : "s"}</>}
                </div>
                {importResult.skipped.slice(0, 5).map((s, i) => (
                  <div key={i} style={{ color: "var(--muted)", marginTop: 4 }}>Row {s.row}: {s.title} — {s.reason}</div>
                ))}
                {importResult.warnings.slice(0, 8).map((w, i) => (
                  <div key={i} style={{ color: "var(--amber)", marginTop: 4 }}>Row {w.row}: {w.message}</div>
                ))}
              </>
            )}
          </div>
        </div>
      )}

      {showNew && canManage && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-head"><h2>New risk</h2></div>
          <div className="card-body">
            <form onSubmit={createRisk} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 10 }}>
              <input name="title" placeholder="Risk title" required />
              <select name="rtype" defaultValue="control_gap">
                {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <select name="likelihood" defaultValue="3">
                {SCALE.map((n) => <option key={n} value={n}>Likelihood {n}</option>)}
              </select>
              <select name="impact" defaultValue="3">
                {SCALE.map((n) => <option key={n} value={n}>Impact {n}</option>)}
              </select>
              <select name="owner" defaultValue="">
                <option value="">Owner…</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
              </select>
              <select name="control" defaultValue="">
                <option value="">Related control…</option>
                {controls.map((c) => <option key={c.id} value={c.id}>{c.framework_name} · {c.label}</option>)}
              </select>
              <input name="due" type="date" />
              <div />
              <textarea name="description" rows={2} placeholder="Description" style={{ gridColumn: "1 / -1" }} />
              <textarea name="plan" rows={2} placeholder="Mitigation plan" style={{ gridColumn: "1 / -1" }} />
              <button className="btn primary" style={{ gridColumn: "1 / -1" }}>Create risk</button>
            </form>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h2>Risk register</h2>
          <span className="eyebrow">{shown.length} shown</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {loading ? <div className="loading">Loading risks…</div> :
           shown.length === 0 ? <div className="empty">No risks in this view.</div> : (
            <table>
              <thead>
                <tr>
                  <th>Risk</th>
                  <th style={{ width: 100 }}>Rating</th>
                  <th style={{ width: 140 }}>Owner</th>
                  <th style={{ width: 110 }}>Due</th>
                  <th style={{ width: 130 }}>Status</th>
                  <th style={{ width: 70 }}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id} onClick={() => openRisk(r)}
                      style={{ cursor: "pointer", background: sel?.id === r.id ? "#f7f9fb" : undefined }}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{r.title}</div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                        {TYPES.find((t) => t[0] === r.risk_type)?.[1]}
                        {r.control_label ? <span className="evi-chip" style={{ marginLeft: 8 }}><b>{r.control_label}</b></span> : null}
                        {r.jira_key ? <span className="mono" style={{ marginLeft: 8 }}>{r.jira_key}</span> : null}
                      </div>
                    </td>
                    <td>
                      <span className={`badge ${RATING_CLS[r.rating]}`}>
                        <span className="dot" />{r.rating} · {r.score}
                      </span>
                    </td>
                    <td style={{ color: r.owner_name ? "var(--ink)" : "var(--muted)" }}>{r.owner_name || "Unassigned"}</td>
                    <td className="mono" style={{ color: r.is_overdue ? "var(--red)" : undefined }}>
                      {r.due_date || "—"}
                    </td>
                    <td>{statusBadge(r.status)}</td>
                    <td className="mono" style={{ color: "var(--muted)" }}>{r.note_count || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {sel && (
        <div className="card" style={{ marginTop: 18 }}>
          <div className="card-head">
            <div>
              <h2>{sel.title}</h2>
              <div className="eyebrow" style={{ marginTop: 3 }}>
                identified {sel.identified_on} · by {sel.created_by_name || "—"}
                {sel.closed_at ? ` · closed ${sel.closed_at.slice(0, 10)}` : ""}
              </div>
            </div>
            <button className="btn small" onClick={() => setSel(null)}>Close</button>
          </div>
          <div className="card-body">
            {sel.description && <p style={{ marginTop: 0, fontSize: 13.5 }}>{sel.description}</p>}

            {canEditRisk(sel) ? (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
                <select value={sel.status} onChange={(e) => patch(sel, { status: e.target.value })}>
                  {STATUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <select value={sel.treatment} onChange={(e) => patch(sel, { treatment: e.target.value })}>
                  {TREATMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <select value={sel.likelihood} onChange={(e) => patch(sel, { likelihood: Number(e.target.value) })}>
                  {SCALE.map((n) => <option key={n} value={n}>Likelihood {n}</option>)}
                </select>
                <select value={sel.impact} onChange={(e) => patch(sel, { impact: Number(e.target.value) })}>
                  {SCALE.map((n) => <option key={n} value={n}>Impact {n}</option>)}
                </select>
                <select value={sel.owner || ""} onChange={(e) => patch(sel, { owner: e.target.value || null })}>
                  <option value="">Owner…</option>
                  {users.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                </select>
                <input type="date" value={sel.due_date || ""} onChange={(e) => patch(sel, { due_date: e.target.value || null })} />
                <input className="mini-input" placeholder="Jira key" defaultValue={sel.jira_key}
                       onBlur={(e) => e.target.value !== sel.jira_key && patch(sel, { jira_key: e.target.value.trim() })} />
              </div>
            ) : (
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 14, fontSize: 13 }}>
                <span>{statusBadge(sel.status)}</span>
                <span className="mono">L{sel.likelihood} × I{sel.impact} = {sel.score}</span>
                <span>{TREATMENTS.find((t) => t[0] === sel.treatment)?.[1]}</span>
              </div>
            )}

            <div className="eyebrow" style={{ marginBottom: 6 }}>Mitigation plan</div>
            {canEditRisk(sel) ? (
              <>
                <textarea rows={3} style={{ width: "100%" }} value={planDraft}
                          onChange={(e) => setPlanDraft(e.target.value)} />
                {planDraft !== (sel.mitigation_plan || "") && (
                  <button className="btn small" style={{ marginTop: 6 }}
                          onClick={() => patch(sel, { mitigation_plan: planDraft })}>
                    Save plan
                  </button>
                )}
              </>
            ) : (
              <p style={{ marginTop: 0, fontSize: 13.5, color: sel.mitigation_plan ? "var(--ink)" : "var(--muted)" }}>
                {sel.mitigation_plan || "No plan recorded yet."}
              </p>
            )}

            <div className="eyebrow" style={{ margin: "16px 0 6px" }}>Notes</div>
            {notes.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13 }}>No notes yet.</div>
            ) : (
              notes.map((n) => (
                <div key={n.id} style={{ borderTop: "1px solid var(--line)", padding: "8px 0" }}>
                  <div style={{ fontSize: 12, color: "var(--muted)" }} className="mono">
                    {n.author_name || "—"} · {n.created_at.slice(0, 10)}
                  </div>
                  <div style={{ fontSize: 13.5, marginTop: 3 }}>{n.text}</div>
                </div>
              ))
            )}
            <form onSubmit={addNote} style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <input style={{ flex: 1 }} placeholder="Add a progress note…"
                     value={noteText} onChange={(e) => setNoteText(e.target.value)} />
              <button className="btn small" disabled={!noteText.trim()}>Add note</button>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
