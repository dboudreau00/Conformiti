import { useEffect, useState } from "react";
import api from "../api/client.js";

export default function Jira({ me }) {
  const isManager = !!me?.capabilities?.manage_users;
  const [config, setConfig] = useState(null);
  const [form, setForm] = useState({ base_url: "", email: "", api_token: "", enabled: false });
  const [boards, setBoards] = useState([]);
  const [active, setActive] = useState(null);
  const [issues, setIssues] = useState(null);
  const [issueErr, setIssueErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isManager) {
      api.get("/integrations/jira/config/").then((r) => {
        setConfig(r.data);
        setForm({ base_url: r.data.base_url || "", email: r.data.email || "", api_token: "", enabled: r.data.enabled });
      }).catch(() => {});
    }
    loadBoards();
  }, [isManager]);

  function loadBoards(selectId) {
    api.get("/integrations/jira/boards/").then((r) => {
      const list = r.data.results || r.data;
      setBoards(list);
      const pick = selectId ? list.find((b) => b.id === selectId) : list[0];
      if (pick) open(pick);
    });
  }

  function open(b) {
    setActive(b); setIssues(null); setIssueErr(null);
    api.get(`/integrations/jira/boards/${b.id}/issues/`)
      .then((r) => setIssues(r.data))
      .catch((e) => setIssueErr(e?.response?.data?.detail || "Couldn't load issues from Jira."));
  }

  async function saveConfig() {
    setBusy(true); setMsg(null);
    try {
      const payload = { base_url: form.base_url, email: form.email, enabled: form.enabled };
      if (form.api_token) payload.api_token = form.api_token;
      const { data } = await api.patch("/integrations/jira/config/", payload);
      setConfig(data);
      setForm({ ...form, api_token: "" });
      setMsg({ ok: true, text: "Configuration saved." });
    } catch (e) {
      setMsg({ ok: false, text: "Couldn't save — check the base URL format." });
    } finally { setBusy(false); }
  }

  async function testConnection() {
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.post("/integrations/jira/test/");
      setMsg({ ok: true, text: data.detail });
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Connection test failed." });
    } finally { setBusy(false); }
  }

  async function addBoard(e) {
    e.preventDefault();
    const f = e.target;
    const { data } = await api.post("/integrations/jira/boards/", {
      board_id: Number(f.board_id.value),
      name: f.name.value,
    });
    f.reset();
    loadBoards(data.id);
  }

  async function removeBoard(b) {
    await api.delete(`/integrations/jira/boards/${b.id}/`);
    setActive(null); setIssues(null);
    loadBoards();
  }

  const configured = config ? config.enabled && config.base_url && config.has_token : boards.length > 0;

  return (
    <>
      {isManager && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-head">
            <h2>Jira connection</h2>
            <span className={"badge " + (config?.enabled ? "ok" : "neutral")}>
              <span className="dot" />{config?.enabled ? "enabled" : "disabled"}
            </span>
          </div>
          <div className="card-body">
            <div className="acct-grid2">
              <div className="field">
                <label>Base URL</label>
                <input placeholder="https://your-team.atlassian.net" value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
              </div>
              <div className="field">
                <label>Account email</label>
                <input type="email" placeholder="you@company.com" value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
            </div>
            <div className="field">
              <label>API token</label>
              <input type="password" value={form.api_token}
                placeholder={config?.has_token ? "•••••• (saved — leave blank to keep)" : "Paste an Atlassian API token"}
                onChange={(e) => setForm({ ...form, api_token: e.target.value })} />
              <div className="hint">
                Create a scoped token at id.atlassian.com → Security → API tokens. It's stored
                server-side and never sent to the browser.
              </div>
            </div>
            <div className="field" style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <input id="jira-en" type="checkbox" style={{ width: "auto" }} checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              <label htmlFor="jira-en" style={{ margin: 0 }}>Integration enabled</label>
            </div>
            {msg && <div className={msg.ok ? "notice ok" : "error"}>{msg.text}</div>}
            <div className="toolbar" style={{ margin: 0 }}>
              <button className="btn primary" onClick={saveConfig} disabled={busy}>Save configuration</button>
              <button className="btn" onClick={testConnection} disabled={busy}>Test connection</button>
            </div>
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <div className="card-head">
            <h2>{active ? `${active.name} — issues` : "Board issues"}</h2>
            {active && <button className="btn small" onClick={() => open(active)}>Refresh</button>}
          </div>
          <div className="card-body" style={{ paddingTop: 6 }}>
            {!active && (
              <div className="empty">
                {configured
                  ? "Add a board on the right to see its issues here."
                  : "The Jira integration isn't configured yet. An administrator can connect it above."}
              </div>
            )}
            {active && issueErr && <div className="error" style={{ marginTop: 12 }}>{issueErr}</div>}
            {active && !issues && !issueErr && <div className="loading">Fetching issues from Jira…</div>}
            {issues && (
              <>
                <table>
                  <thead>
                    <tr><th style={{ width: 90 }}>Key</th><th>Summary</th><th style={{ width: 120 }}>Status</th><th style={{ width: 140 }}>Assignee</th><th style={{ width: 100 }}>Updated</th></tr>
                  </thead>
                  <tbody>
                    {issues.issues.map((i) => (
                      <tr key={i.key}>
                        <td className="cid">{i.key}</td>
                        <td>
                          <div style={{ fontWeight: 500 }}>{i.summary}</div>
                          <div style={{ fontSize: 12, color: "var(--muted)" }}>{i.type}{i.priority ? ` · ${i.priority}` : ""}</div>
                        </td>
                        <td><span className="badge neutral">{i.status}</span></td>
                        <td style={{ fontSize: 13 }}>{i.assignee || <span style={{ color: "var(--muted)" }}>unassigned</span>}</td>
                        <td className="mono" style={{ fontSize: 12 }}>{(i.updated || "").slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {issues.issues.length === 0 && <div className="empty">This board has no issues.</div>}
              </>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h2>Tracked boards</h2><span className="eyebrow">jira agile boards</span></div>
          <div className="card-body">
            {boards.map((b) => (
              <div key={b.id} className={"tree-row" + (active?.id === b.id ? " selected" : "")} onClick={() => open(b)}>
                <span className="tw">◈</span> {b.name}
                <span className="cnt">#{b.board_id}</span>
                {isManager && (
                  <button className="btn small" style={{ marginLeft: 8 }}
                    onClick={(e) => { e.stopPropagation(); removeBoard(b); }}>
                    Remove
                  </button>
                )}
              </div>
            ))}
            {boards.length === 0 && <div className="empty">No boards tracked yet.</div>}
            {isManager && (
              <form onSubmit={addBoard} style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
                <div className="acct-grid2">
                  <div className="field"><label>Board ID</label><input name="board_id" type="number" min="1" required placeholder="e.g. 12" /></div>
                  <div className="field"><label>Name</label><input name="name" required placeholder="e.g. Security backlog" /></div>
                </div>
                <button className="btn primary small">Track board</button>
                <div className="hint" style={{ marginTop: 8 }}>
                  The board ID is the number in the Jira board URL (…/boards/12).
                </div>
              </form>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
