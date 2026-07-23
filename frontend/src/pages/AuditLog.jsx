import { useEffect, useState } from "react";
import api from "../api/client.js";

const ACTION_BADGE = { create: "ok", update: "neutral", delete: "overdue" };

function fmtWhen(ts) {
  return ts ? ts.slice(0, 16).replace("T", " ") : "";
}

export default function AuditLog({ me }) {
  const [rows, setRows] = useState([]);
  const [next, setNext] = useState(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState({ actions: [], object_types: [], users: [] });
  const [f, setF] = useState({ action: "", type: "", user: "", days: "30", q: "" });
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);

  const caps = me?.capabilities || {};
  const canSee = caps.manage_users || caps.auditor || caps.view_all;

  function query(p) {
    const parts = [`page=${p}`];
    if (f.action) parts.push(`action=${encodeURIComponent(f.action)}`);
    if (f.type) parts.push(`object_type=${encodeURIComponent(f.type)}`);
    if (f.user) parts.push(`user=${encodeURIComponent(f.user)}`);
    if (f.days) parts.push(`days=${encodeURIComponent(f.days)}`);
    if (f.q) parts.push(`search=${encodeURIComponent(f.q)}`);
    return `/audit-log/?${parts.join("&")}`;
  }

  async function load(reset) {
    setLoading(true);
    const p = reset ? 1 : page + 1;
    try {
      const { data } = await api.get(query(p));
      const results = data.results || data;
      setRows(reset ? results : rows.concat(results));
      setNext(data.next || null);
      setTotal(data.count ?? results.length);
      setPage(p);
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(true); }, [f]);
  useEffect(() => {
    api.get("/audit-log/facets/").then((r) => setFacets(r.data)).catch(() => {});
  }, []);

  if (!canSee || denied) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="empty">
            The audit trail is visible to administrators, auditors, and
            managers with view-all access. Ask an administrator if you need it.
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="pagehead">
        <div className="sub">
          Immutable record of every change made through the API — who did what,
          to which record, from where. Entries are written server-side and
          cannot be edited or deleted from the app.
        </div>
      </div>

      <div className="toolbar">
        <select value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}>
          <option value="">All actions</option>
          {facets.actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>
          <option value="">All record types</option>
          {facets.object_types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={f.user} onChange={(e) => setF({ ...f, user: e.target.value })}>
          <option value="">All users</option>
          {facets.users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
        </select>
        <select value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })}>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 90 days</option>
          <option value="">All time</option>
        </select>
        <input placeholder="Search detail, record, user, IP…" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") setF({ ...f, q }); }}
               style={{ width: 240 }} />
        <button className="btn small" onClick={() => setF({ ...f, q })}>Search</button>
        {(f.q || f.action || f.type || f.user) && (
          <button className="btn small" onClick={() => { setQ(""); setF({ action: "", type: "", user: "", days: f.days, q: "" }); }}>
            Clear
          </button>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Audit trail</h2>
          <span className="eyebrow">{total} entr{total === 1 ? "y" : "ies"}</span>
        </div>
        <div className="card-body" style={{ padding: 0, overflowX: "auto" }}>
          {loading && rows.length === 0 ? (
            <div className="loading">Loading audit trail…</div>
          ) : rows.length === 0 ? (
            <div className="empty">
              No entries match. New entries appear automatically as people
              create, update, or delete records.
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th style={{ width: 140 }}>When</th>
                  <th style={{ width: 160 }}>Actor</th>
                  <th style={{ width: 95 }}>Action</th>
                  <th style={{ width: 190 }}>Record</th>
                  <th>Detail</th>
                  <th style={{ width: 120 }}>IP</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono" style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{fmtWhen(r.timestamp)}</td>
                    <td>
                      <div style={{ fontWeight: 500, fontSize: 13.5 }}>{r.user_name}</div>
                      {r.username ? <div className="mono" style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.username}</div> : null}
                    </td>
                    <td>
                      <span className={"badge " + (ACTION_BADGE[r.action] || "neutral")}>
                        <span className="dot" />{r.action}
                      </span>
                    </td>
                    <td className="mono" style={{ fontSize: 12.5 }}>
                      {r.object_type}{r.object_id ? ` #${r.object_id}` : ""}
                    </td>
                    <td style={{ fontSize: 13, color: r.detail ? "var(--ink)" : "var(--muted)" }}>
                      {r.detail || "—"}
                    </td>
                    <td className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{r.ip_address || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {next && (
          <div style={{ padding: "12px 18px", borderTop: "1px solid var(--line)" }}>
            <button className="btn small" onClick={() => load(false)} disabled={loading}>
              {loading ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
