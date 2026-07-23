import { useEffect, useState } from "react";
import api from "../api/client.js";

const CAP_LABELS = [
  ["can_manage_users", "users"],
  ["can_manage_frameworks", "frameworks"],
  ["can_manage_documents", "documents"],
  ["can_manage_folders", "folders"],
  ["can_view_all", "view all"],
  ["is_auditor", "auditor"],
];

export default function Users({ me }) {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [banner, setBanner] = useState(null);        // {kind:"ok"|"err", text}
  const [pwFor, setPwFor] = useState(null);          // user id with password editor open
  const [pwValue, setPwValue] = useState("");
  const [formErr, setFormErr] = useState(null);

  const isAdmin = me?.capabilities?.manage_users;

  async function loadUsers() {
    setLoading(true);
    try {
      let page = 1, all = [];
      for (;;) {
        const r = await api.get(`/users/?page=${page}`);
        all = all.concat(r.data.results || r.data);
        if (!r.data.next || page >= 5) break;
        page += 1;
      }
      setUsers(all);
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
    api.get("/roles/").then((r) => setRoles(r.data.results || r.data)).catch(() => {});
  }, []);

  function fail(e, fallback) {
    const d = e?.response?.data;
    const text = d?.detail || (typeof d === "object" && d ? Object.values(d).flat().join(" ") : null);
    setBanner({ kind: "err", text: text || fallback });
  }

  function ok(text) {
    setBanner({ kind: "ok", text });
  }

  const canTouch = (u) => !(u.is_superuser && !me?.is_superuser);

  async function patchUser(u, payload, doneMsg) {
    try {
      await api.patch(`/users/${u.id}/`, payload);
      if (doneMsg) ok(doneMsg);
      loadUsers();
    } catch (e) {
      fail(e, "Update failed.");
    }
  }

  async function removeUser(u) {
    if (!window.confirm(`Delete ${u.username}? This cannot be undone. Deactivating is usually safer.`)) return;
    try {
      await api.delete(`/users/${u.id}/`);
      ok(`Deleted ${u.username}.`);
      loadUsers();
    } catch (e) {
      fail(e, "Delete failed.");
    }
  }

  async function savePassword(u) {
    try {
      await api.patch(`/users/${u.id}/`, { password: pwValue });
      ok(`Password set for ${u.username}. Share it with them securely.`);
      setPwFor(null);
      setPwValue("");
    } catch (e) {
      fail(e, "Password rejected.");
    }
  }

  async function resetMfa(u) {
    if (!window.confirm(`Reset two-factor for ${u.username}? They'll need to set it up again on next sign-in.`)) return;
    try {
      await api.post(`/users/${u.id}/reset_mfa/`);
      ok(`MFA reset for ${u.username}.`);
      loadUsers();
    } catch (e) {
      fail(e, "Couldn't reset MFA.");
    }
  }

  async function createUser(e) {
    e.preventDefault();
    setFormErr(null);
    const f = e.target;
    const payload = {
      username: f.username.value.trim(),
      first_name: f.first.value.trim(),
      last_name: f.last.value.trim(),
      email: f.email.value.trim(),
      job_title: f.job.value.trim(),
      role: f.role.value || null,
      password: f.password.value,
      is_active: true,
    };
    try {
      await api.post("/users/", payload);
      ok(`Created ${payload.username}.`);
      setShowNew(false);
      f.reset();
      loadUsers();
    } catch (err) {
      const d = err?.response?.data;
      setFormErr(
        d && typeof d === "object"
          ? Object.entries(d).map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`).join(" · ")
          : "Could not create the user."
      );
    }
  }

  if (!isAdmin || denied) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="empty">
            User management needs the <b>manage users</b> capability
            (Administrator role). Ask an administrator for access.
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="pagehead">
        <div className="sub">
          Create accounts, assign roles, and control who can sign in. Folder-level
          access is granted per folder on the Documents page.
        </div>
        <div className="toolbar">
          <button className="btn primary small" onClick={() => { setShowNew((v) => !v); setFormErr(null); }}>
            {showNew ? "Cancel" : "New user"}
          </button>
        </div>
      </div>

      {banner && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-body" style={{ display: "flex", justifyContent: "space-between", gap: 12,
                color: banner.kind === "err" ? "var(--red)" : "var(--accent-2)", fontSize: 13.5 }}>
            <span>{banner.text}</span>
            <button className="btn small" onClick={() => setBanner(null)}>Dismiss</button>
          </div>
        </div>
      )}

      {showNew && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-head"><h2>New user</h2><span className="eyebrow">password is required — share it securely</span></div>
          <div className="card-body">
            <form onSubmit={createUser} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              <input name="username" placeholder="Username *" required />
              <input name="first" placeholder="First name" />
              <input name="last" placeholder="Last name" />
              <input name="email" type="email" placeholder="Email" />
              <input name="job" placeholder="Job title" />
              <select name="role" defaultValue="" required>
                <option value="" disabled>Role *</option>
                {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
              <input name="password" type="password" placeholder="Temporary password *" required minLength={8}
                     style={{ gridColumn: "1 / span 2" }} />
              <button className="btn primary">Create user</button>
              {formErr && <div style={{ gridColumn: "1 / -1", color: "var(--red)", fontSize: 13 }}>{formErr}</div>}
            </form>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h2>Users</h2>
          <span className="eyebrow">{users.filter((u) => u.is_active).length} active · {users.length} total</span>
        </div>
        <div className="card-body" style={{ padding: 0, overflowX: "auto" }}>
          {loading ? <div className="loading">Loading users…</div> : (
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th style={{ width: 150 }}>Job title</th>
                  <th style={{ width: 190 }}>Role</th>
                  <th style={{ width: 115 }}>Last login</th>
                  <th style={{ width: 95 }}>Status</th>
                  <th style={{ width: 80 }}>2FA</th>
                  <th style={{ width: 320 }}></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const self = u.id === me?.id;
                  const touchable = canTouch(u);
                  return (
                    <tr key={u.id}>
                      <td>
                        <div style={{ fontWeight: 500 }}>
                          <span className="mono">{u.username}</span>
                          {u.is_superuser ? <span className="badge neutral" style={{ marginLeft: 8 }}>superuser</span> : null}
                          {self ? <span className="badge ok" style={{ marginLeft: 8 }}><span className="dot" />you</span> : null}
                        </div>
                        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>
                          {u.full_name || "—"}{u.email ? ` · ${u.email}` : ""}
                        </div>
                      </td>
                      <td style={{ color: u.job_title ? "var(--ink)" : "var(--muted)", fontSize: 13 }}>{u.job_title || "—"}</td>
                      <td>
                        <select value={u.role || ""} disabled={self || !touchable}
                                onChange={(e) => patchUser(u, { role: e.target.value || null }, `Role updated for ${u.username}.`)}>
                          <option value="">No role</option>
                          {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                        </select>
                      </td>
                      <td className="mono" style={{ color: "var(--muted)" }}>
                        {u.last_login ? u.last_login.slice(0, 10) : "never"}
                      </td>
                      <td>
                        {u.is_active
                          ? <span className="badge ok"><span className="dot" />active</span>
                          : <span className="badge neutral"><span className="dot" />inactive</span>}
                      </td>
                      <td>
                        {u.mfa_enabled
                          ? <span className="badge ok"><span className="dot" />on</span>
                          : <span className="badge neutral" style={{ color: "var(--muted)" }}>off</span>}
                      </td>
                      <td>
                        {pwFor === u.id ? (
                          <div className="row-actions">
                            <input className="mini-input" type="password" placeholder="New password"
                                   value={pwValue} onChange={(e) => setPwValue(e.target.value)} style={{ width: 150 }} />
                            <button className="btn small" disabled={pwValue.length < 8} onClick={() => savePassword(u)}>Save</button>
                            <button className="btn small" onClick={() => { setPwFor(null); setPwValue(""); }}>Cancel</button>
                          </div>
                        ) : (
                          <div className="row-actions" style={{ justifyContent: "flex-end" }}>
                            {touchable && <button className="btn small" onClick={() => { setPwFor(u.id); setPwValue(""); }}>Set password</button>}
                            {touchable && !self && (
                              <button className="btn small"
                                      onClick={() => patchUser(u, { is_active: !u.is_active },
                                        `${u.username} ${u.is_active ? "deactivated" : "activated"}.`)}>
                                {u.is_active ? "Deactivate" : "Activate"}
                              </button>
                            )}
                            {touchable && u.mfa_enabled && (
                              <button className="btn small" onClick={() => resetMfa(u)}>Reset 2FA</button>
                            )}
                            {touchable && !self && !u.is_superuser && (
                              <button className="btn small" onClick={() => removeUser(u)}>Delete</button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 18 }}>
        <div className="card-head"><h2>Roles &amp; permissions</h2><span className="eyebrow">what each role can do</span></div>
        <div className="card-body" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr><th style={{ width: 190 }}>Role</th><th>Description</th><th style={{ width: 330 }}>Capabilities</th></tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.id}>
                  <td style={{ fontWeight: 500 }}>
                    {r.name}
                    {r.is_system ? <span className="badge neutral" style={{ marginLeft: 8 }}>built-in</span> : null}
                  </td>
                  <td style={{ color: "var(--muted)", fontSize: 13 }}>{r.description || "—"}</td>
                  <td>
                    {CAP_LABELS.filter(([k]) => r[k]).map(([k, label]) => (
                      <span key={k} className="evi-chip"><b>{label}</b></span>
                    ))}
                    {CAP_LABELS.every(([k]) => !r[k]) && (
                      <span style={{ color: "var(--muted)", fontSize: 12.5 }}>read-only (folder grants apply)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
