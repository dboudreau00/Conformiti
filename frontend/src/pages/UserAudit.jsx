import { useEffect, useState } from "react";
import api from "../api/client.js";

const DECISIONS = [
  { v: "pending", label: "Pending" },
  { v: "keep", label: "Keep" },
  { v: "modify", label: "Modify" },
  { v: "revoke", label: "Revoke" },
];

function fmtDate(s) {
  return s ? s.slice(0, 10) : "never";
}

export default function UserAudit() {
  const [reviews, setReviews] = useState([]);
  const [review, setReview] = useState(null);
  const [items, setItems] = useState([]);
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState(null);
  const [denied, setDenied] = useState(false);

  function loadReviews(selectId) {
    api.get("/access-reviews/")
      .then((r) => {
        const list = r.data.results || r.data;
        setReviews(list);
        const pick = selectId
          ? list.find((x) => x.id === selectId)
          : list.find((x) => x.status === "open") || list[0];
        if (pick) open(pick);
      })
      .catch((e) => { if (e?.response?.status === 403) setDenied(true); });
  }

  useEffect(() => { loadReviews(); }, []);

  function open(rev) {
    setReview(rev); setMsg(null);
    api.get(`/access-review-items/?review=${rev.id}`)
      .then((r) => setItems(r.data.results || r.data));
  }

  async function startReview() {
    const name = newName.trim() || `Access review — ${new Date().toISOString().slice(0, 10)}`;
    const { data } = await api.post("/access-reviews/", { name });
    setNewName("");
    loadReviews(data.id);
  }

  async function saveItem(item, patch) {
    const { data } = await api.patch(`/access-review-items/${item.id}/`, patch);
    setItems(items.map((i) => (i.id === item.id ? data : i)));
  }

  async function complete() {
    setMsg(null);
    try {
      const { data } = await api.post(`/access-reviews/${review.id}/complete/`);
      setReview(data);
      setReviews(reviews.map((r) => (r.id === data.id ? data : r)));
      setMsg({ ok: true, text: "Review completed — the grid is now read-only evidence." });
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Couldn't complete the review." });
    }
  }

  async function exportCsv() {
    const r = await api.get(`/access-reviews/${review.id}/export/`, { responseType: "blob" });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `access-review-${review.id}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (denied) {
    return (
      <div className="empty">
        Access reviews are limited to administrators and auditors.
        Ask an administrator if you need this.
      </div>
    );
  }

  const decided = items.filter((i) => i.decision !== "pending").length;
  const readOnly = review?.status === "completed";

  return (
    <>
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-head"><h2>Access reviews</h2><span className="eyebrow">user account audits</span></div>
        <div className="card-body">
          <div className="toolbar">
            <select
              style={{ maxWidth: 340 }}
              value={review?.id || ""}
              onChange={(e) => {
                const r = reviews.find((x) => x.id === Number(e.target.value));
                if (r) open(r);
              }}
            >
              {reviews.length === 0 && <option value="">No reviews yet</option>}
              {reviews.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {r.status} ({r.decided_count}/{r.item_count})
                </option>
              ))}
            </select>
            <input
              style={{ maxWidth: 280 }}
              placeholder="New review name (e.g. Q3 2026 access review)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button className="btn primary" onClick={startReview}>Start new review</button>
          </div>
          <div className="cov-note">
            Starting a review snapshots every user account — role, activity, folder grants and
            capabilities — into a grid. Record a decision per row, then export the CSV as audit evidence.
          </div>
        </div>
      </div>

      {review && (
        <div className="card">
          <div className="card-head">
            <h2>{review.name}</h2>
            <div className="toolbar" style={{ margin: 0 }}>
              <span className={"badge " + (readOnly ? "ok" : decided === items.length && items.length ? "ok" : "soon")}>
                <span className="dot" />{decided}/{items.length} decided
              </span>
              <button className="btn small" onClick={exportCsv}>Export CSV</button>
              {!readOnly && (
                <button className="btn small primary" onClick={complete}>Complete review</button>
              )}
            </div>
          </div>
          <div className="card-body" style={{ paddingTop: 6, overflowX: "auto" }}>
            {msg && <div className={msg.ok ? "notice ok" : "error"}>{msg.text}</div>}
            <table>
              <thead>
                <tr>
                  <th>User</th><th>Role</th><th>Active</th><th>Last login</th>
                  <th>Grants</th><th>Capabilities</th><th style={{ width: 130 }}>Decision</th>
                  <th style={{ width: 220 }}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{it.full_name || it.username}</div>
                      <div className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{it.username} · {it.email}</div>
                    </td>
                    <td>{it.role_name || "—"}</td>
                    <td>
                      {it.is_active
                        ? <span className="badge ok"><span className="dot" />yes</span>
                        : <span className="badge overdue"><span className="dot" />no</span>}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>{fmtDate(it.last_login)}</td>
                    <td className="mono">{it.folder_grants}</td>
                    <td style={{ fontSize: 12, color: "var(--muted)" }}>{it.capabilities || "—"}</td>
                    <td>
                      <select
                        className={"decision " + it.decision}
                        value={it.decision}
                        disabled={readOnly}
                        onChange={(e) => saveItem(it, { decision: e.target.value })}
                      >
                        {DECISIONS.map((d) => <option key={d.v} value={d.v}>{d.label}</option>)}
                      </select>
                    </td>
                    <td>
                      <input
                        className="mini-input"
                        defaultValue={it.decision_notes}
                        disabled={readOnly}
                        placeholder="Reviewer note"
                        onBlur={(e) => {
                          if (e.target.value !== it.decision_notes) {
                            saveItem(it, { decision_notes: e.target.value });
                          }
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {items.length === 0 && <div className="empty">No rows — start a review above.</div>}
          </div>
        </div>
      )}
    </>
  );
}
