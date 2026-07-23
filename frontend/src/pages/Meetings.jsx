import { useEffect, useState } from "react";
import api from "../api/client.js";

const STATUS = {
  complete: { cls: "ok", label: "Complete" },
  on_track: { cls: "ok", label: "On track" },
  behind: { cls: "soon", label: "Behind" },
};

export default function Meetings({ me }) {
  const [series, setSeries] = useState([]);
  const [active, setActive] = useState(null);
  const [minutes, setMinutes] = useState([]);
  const [users, setUsers] = useState([]);
  const [showNewSeries, setShowNewSeries] = useState(false);
  const canEdit = !!me?.capabilities?.manage_documents;

  function loadSeries(selectId) {
    api.get("/meeting-series/").then((r) => {
      const list = r.data.results || r.data;
      setSeries(list);
      const pick = selectId ? list.find((s) => s.id === selectId) : list[0];
      if (pick) open(pick);
    });
  }

  useEffect(() => {
    loadSeries();
    api.get("/users/").then((r) => setUsers(r.data.results || r.data)).catch(() => setUsers([]));
  }, []);

  function open(s) {
    setActive(s);
    api.get(`/meeting-minutes/?series=${s.id}`).then((r) => setMinutes(r.data.results || r.data));
  }

  async function addSeries(e) {
    e.preventDefault();
    const f = e.target;
    const payload = {
      name: f.name.value,
      required_per_year: Number(f.required.value) || 4,
      description: f.description.value,
    };
    if (f.owner && f.owner.value) payload.owner = Number(f.owner.value);
    const { data } = await api.post("/meeting-series/", payload);
    f.reset(); setShowNewSeries(false);
    loadSeries(data.id);
  }

  async function addMinute(e) {
    e.preventDefault();
    const f = e.target;
    const fd = new FormData();
    fd.append("series", active.id);
    fd.append("date", f.date.value);
    fd.append("title", f.title.value);
    fd.append("attendees", f.attendees.value);
    fd.append("notes", f.notes.value);
    if (f.file.files[0]) fd.append("file", f.file.files[0]);
    await api.post("/meeting-minutes/", fd);
    f.reset();
    loadSeries(active.id);
  }

  return (
    <div className="grid-2">
      <div>
        {active && (
          <div className="card">
            <div className="card-head">
              <h2>{active.name}</h2>
              <span className="badge neutral">{active.held_this_year}/{active.required_per_year} this year</span>
            </div>
            <div className="card-body">
              {active.description && <div className="cov-note" style={{ marginTop: 0, marginBottom: 14 }}>{active.description}</div>}
              {minutes.map((m) => (
                <div className="review-item" key={m.id}>
                  <span className="badge neutral mono">{m.date}</span>
                  <div className="meta">
                    <div className="name">{m.title || "Meeting minutes"}</div>
                    <div className="path">{m.attendees || "attendees not recorded"}</div>
                    {m.notes && <div style={{ fontSize: 13, color: "var(--ink-2)", marginTop: 4 }}>{m.notes}</div>}
                  </div>
                  {m.file && <a className="btn small" href={m.file} target="_blank" rel="noreferrer">Open file</a>}
                </div>
              ))}
              {minutes.length === 0 && <div className="empty">No minutes recorded yet this year.</div>}
            </div>
          </div>
        )}

        {active && canEdit && (
          <div className="card" style={{ marginTop: 20 }}>
            <div className="card-head"><h2>Record minutes</h2><span className="eyebrow">{active.name}</span></div>
            <div className="card-body">
              <form onSubmit={addMinute}>
                <div className="acct-grid2">
                  <div className="field"><label>Date</label><input name="date" type="date" required /></div>
                  <div className="field"><label>Title</label><input name="title" placeholder="e.g. Q3 security steering" /></div>
                </div>
                <div className="field"><label>Attendees</label><input name="attendees" placeholder="Ada Admin, Mia Manager…" /></div>
                <div className="field"><label>Notes / decisions</label><textarea name="notes" rows="3" placeholder="Key points and decisions" /></div>
                <div className="field"><label>Attachment (optional)</label><input name="file" type="file" /></div>
                <button className="btn primary">Save minutes</button>
              </form>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Meeting cadences</h2>
          {canEdit && (
            <button className="btn small" onClick={() => setShowNewSeries(!showNewSeries)}>
              {showNewSeries ? "Cancel" : "New series"}
            </button>
          )}
        </div>
        <div className="card-body">
          {showNewSeries && (
            <form onSubmit={addSeries} style={{ marginBottom: 16, paddingBottom: 14, borderBottom: "1px solid var(--line)" }}>
              <div className="field"><label>Name</label><input name="name" required placeholder="e.g. Vendor Review Board" /></div>
              <div className="acct-grid2">
                <div className="field"><label>Required per year</label><input name="required" type="number" min="1" max="52" defaultValue="4" /></div>
                {users.length > 0 && (
                  <div className="field"><label>Owner</label>
                    <select name="owner" defaultValue="">
                      <option value="">—</option>
                      {users.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                    </select>
                  </div>
                )}
              </div>
              <div className="field"><label>Description</label><input name="description" placeholder="What this meeting covers" /></div>
              <button className="btn primary small">Create series</button>
            </form>
          )}
          {series.map((s) => {
            const st = STATUS[s.cadence_status] || STATUS.behind;
            const pct = Math.min(100, Math.round((s.held_this_year / s.required_per_year) * 100));
            return (
              <div
                key={s.id}
                className={"tree-row" + (active?.id === s.id ? " selected" : "")}
                style={{ display: "block", padding: "10px 10px" }}
                onClick={() => open(s)}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontWeight: 600, flex: 1 }}>{s.name}</span>
                  <span className={"badge " + st.cls}><span className="dot" />{st.label}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 7 }}>
                  <div className="progress" style={{ flex: 1 }}><span style={{ width: pct + "%" }} /></div>
                  <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
                    {s.held_this_year}/{s.required_per_year} · exp {s.expected_to_date}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 5 }}>
                  Owner: {s.owner_name || "unassigned"}
                </div>
              </div>
            );
          })}
          {series.length === 0 && <div className="empty">No meeting cadences defined yet.</div>}
          <div className="cov-note">
            "Expected" pro-rates the yearly requirement by the current month, so a quarterly
            meeting shows behind if fewer sessions were held than the calendar demands.
          </div>
        </div>
      </div>
    </div>
  );
}
