import { useEffect, useState } from "react";
import api from "../api/client.js";

export default function Groups({ me }) {
  const [groups, setGroups] = useState([]);
  const [active, setActive] = useState(null);
  const [members, setMembers] = useState([]);
  const [users, setUsers] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const canEdit = !!me?.capabilities?.manage_users;

  function loadGroups(selectId) {
    api.get("/champion-groups/").then((r) => {
      const list = r.data.results || r.data;
      setGroups(list);
      const pick = selectId ? list.find((g) => g.id === selectId) : list[0];
      if (pick) open(pick);
    });
  }

  useEffect(() => {
    loadGroups();
    api.get("/users/").then((r) => setUsers(r.data.results || r.data)).catch(() => setUsers([]));
  }, []);

  function open(g) {
    setActive(g);
    api.get(`/group-members/?group=${g.id}`).then((r) => setMembers(r.data.results || r.data));
  }

  async function addGroup(e) {
    e.preventDefault();
    const f = e.target;
    const payload = { name: f.name.value, purpose: f.purpose.value };
    if (f.owner && f.owner.value) payload.owner = Number(f.owner.value);
    const { data } = await api.post("/champion-groups/", payload);
    f.reset(); setShowNew(false);
    loadGroups(data.id);
  }

  async function addMember(e) {
    e.preventDefault();
    const f = e.target;
    await api.post("/group-members/", {
      group: active.id,
      user: Number(f.user.value),
      department: f.department.value,
      note: f.note.value,
    });
    f.reset();
    open(active);
    loadGroups(active.id);
  }

  async function removeMember(m) {
    await api.delete(`/group-members/${m.id}/`);
    open(active);
    loadGroups(active.id);
  }

  const memberIds = new Set(members.map((m) => m.user));
  const addable = users.filter((u) => !memberIds.has(u.id));

  return (
    <div className="grid-2">
      <div>
        {active && (
          <div className="card">
            <div className="card-head">
              <h2>{active.name}</h2>
              <span className="owner-tag mono">owner: {active.owner_name || "unassigned"}</span>
            </div>
            <div className="card-body" style={{ paddingTop: 6 }}>
              {active.purpose && (
                <div className="cov-note" style={{ marginTop: 8, marginBottom: 10 }}>{active.purpose}</div>
              )}
              <table>
                <thead>
                  <tr><th>Champion</th><th>Department</th><th>Note</th>{canEdit && <th style={{ width: 90 }} />}</tr>
                </thead>
                <tbody>
                  {members.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <div style={{ fontWeight: 500 }}>{m.user_name || m.username}</div>
                        <div className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{m.username}</div>
                      </td>
                      <td><span className="badge neutral">{m.department}</span></td>
                      <td style={{ color: "var(--muted)", fontSize: 13 }}>{m.note || "—"}</td>
                      {canEdit && (
                        <td><button className="btn small" onClick={() => removeMember(m)}>Remove</button></td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
              {members.length === 0 && <div className="empty">No champions in this group yet.</div>}
            </div>
          </div>
        )}

        {active && canEdit && (
          <div className="card" style={{ marginTop: 20 }}>
            <div className="card-head"><h2>Add a champion</h2><span className="eyebrow">{active.name}</span></div>
            <div className="card-body">
              <form onSubmit={addMember}>
                <div className="acct-grid2">
                  <div className="field"><label>User</label>
                    <select name="user" required defaultValue="">
                      <option value="" disabled>Choose a user…</option>
                      {addable.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                    </select>
                  </div>
                  <div className="field"><label>Department they champion</label>
                    <input name="department" required placeholder="e.g. Engineering" />
                  </div>
                </div>
                <div className="field"><label>Note (optional)</label><input name="note" placeholder="e.g. leads secure-code training" /></div>
                <button className="btn primary">Add champion</button>
              </form>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Groups</h2>
          {canEdit && (
            <button className="btn small" onClick={() => setShowNew(!showNew)}>
              {showNew ? "Cancel" : "New group"}
            </button>
          )}
        </div>
        <div className="card-body">
          {showNew && (
            <form onSubmit={addGroup} style={{ marginBottom: 16, paddingBottom: 14, borderBottom: "1px solid var(--line)" }}>
              <div className="field"><label>Name</label><input name="name" required placeholder="e.g. Privacy Champions" /></div>
              {users.length > 0 && (
                <div className="field"><label>Accountable owner</label>
                  <select name="owner" defaultValue="">
                    <option value="">—</option>
                    {users.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                  </select>
                </div>
              )}
              <div className="field"><label>Purpose</label><input name="purpose" placeholder="What this group is accountable for" /></div>
              <button className="btn primary small">Create group</button>
            </form>
          )}
          {groups.map((g) => (
            <div
              key={g.id}
              className={"tree-row" + (active?.id === g.id ? " selected" : "")}
              onClick={() => open(g)}
            >
              <span className="tw">⚑</span> {g.name}
              <span className="cnt">{g.member_count} member{g.member_count === 1 ? "" : "s"}</span>
            </div>
          ))}
          {groups.length === 0 && <div className="empty">No groups yet.</div>}
          <div className="cov-note">
            Each group has one accountable owner; members are champions who carry
            security practices into the department they're tagged with.
          </div>
        </div>
      </div>
    </div>
  );
}
