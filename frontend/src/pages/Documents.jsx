import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import api from "../api/client.js";

const CADENCE = [
  ["none", "No review"], ["monthly", "Monthly"], ["quarterly", "Quarterly"],
  ["semiannual", "Every 6 months"], ["annual", "Annual"], ["biennial", "Every 2 years"],
];

function TreeNode({ node, selected, onSelect, depth = 0 }) {
  const [open, setOpen] = useState(depth < 1);
  const has = node.children?.length > 0;
  return (
    <div>
      <div
        className={"tree-row" + (selected === node.id ? " selected" : "")}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => onSelect(node)}
      >
        <span className="tw" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {has ? (open ? "▾" : "▸") : "·"}
        </span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.name}
        </span>
        {node.document_count > 0 && <span className="cnt">{node.document_count}</span>}
      </div>
      {open && has && node.children.map((c) => (
        <TreeNode key={c.id} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />
      ))}
    </div>
  );
}

function reviewBadge(days) {
  if (days == null) return <span className="badge neutral">no review</span>;
  if (days < 0) return <span className="badge overdue"><span className="dot" />overdue</span>;
  if (days <= 14) return <span className="badge soon"><span className="dot" />{days}d</span>;
  return <span className="badge ok"><span className="dot" />{days}d</span>;
}

export default function Documents({ me }) {
  const [tree, setTree] = useState([]);
  const [folder, setFolder] = useState(null);
  const [docs, setDocs] = useState([]);
  const [roles, setRoles] = useState([]);
  const [users, setUsers] = useState([]);
  const [perms, setPerms] = useState([]);
  const [showPerms, setShowPerms] = useState(false);
  const [fileName, setFileName] = useState("");
  const [mapDoc, setMapDoc] = useState(null);           // doc id with the control-mapping editor open
  const [controlChoices, setControlChoices] = useState([]);
  const uploadRef = useRef();

  const loadTree = () => api.get("/folders/tree/").then((r) => setTree(r.data));
  useEffect(() => {
    loadTree();
    api.get("/roles/").then((r) => setRoles(r.data.results || r.data)).catch(() => {});
    api.get("/users/").then((r) => setUsers(r.data.results || r.data)).catch(() => {});
  }, []);

  function selectFolder(node) {
    setFolder(node);
    setShowPerms(false);
    setMapDoc(null);
    api.get(`/documents/?folder=${node.id}`).then((r) => setDocs(r.data.results || r.data));
  }

  function refreshDocs() {
    if (!folder) return;
    api.get(`/documents/?folder=${folder.id}`).then((r) => setDocs(r.data.results || r.data));
  }

  // --- control mapping (which controls does this document satisfy?) --------
  async function toggleMap(d) {
    if (mapDoc === d.id) { setMapDoc(null); return; }
    setMapDoc(d.id);
    if (!controlChoices.length) {
      const r = await api.get("/control-evidence/choices/");
      setControlChoices(r.data.controls);
    }
  }

  async function addLink(d, controlId) {
    if (!controlId) return;
    try {
      await api.post("/control-evidence/", { control: Number(controlId), document: d.id });
    } catch (e) {
      /* duplicate or permission race — fall through to refresh with server truth */
    }
    refreshDocs();
  }

  async function removeLink(linkId) {
    await api.delete(`/control-evidence/${linkId}/`);
    refreshDocs();
  }

  const canEdit = folder && ["edit", "manage"].includes(folder.my_access);
  const canManage = folder && folder.my_access === "manage";

  async function upload(e) {
    e.preventDefault();
    const form = e.target;
    const fd = new FormData();
    fd.append("folder", folder.id);
    fd.append("name", form.name.value);
    fd.append("review_cadence", form.cadence.value);
    if (form.owner.value) fd.append("owner", form.owner.value);
    fd.append("file", form.file.files[0]);
    await api.post("/documents/", fd);
    form.reset();
    setFileName("");
    selectFolder(folder);
    loadTree();
  }

  async function rename(doc) {
    const name = window.prompt("New document name", doc.name);
    if (!name) return;
    await api.post(`/documents/${doc.id}/rename/`, { name });
    selectFolder(folder);
  }
  async function markReviewed(doc) {
    await api.post(`/documents/${doc.id}/mark_reviewed/`);
    selectFolder(folder);
  }
  async function newVersion(doc, file) {
    const fd = new FormData();
    fd.append("file", file);
    await api.post(`/documents/${doc.id}/new_version/`, fd);
    selectFolder(folder);
  }

  function openPerms() {
    setShowPerms(true);
    api.get(`/folders/${folder.id}/permissions/`).then((r) => setPerms(r.data));
  }
  async function addPerm(e) {
    e.preventDefault();
    const f = e.target;
    const payload = { folder: folder.id, access_level: f.level.value };
    if (f.role.value) payload.role = f.role.value; else return;
    await api.post("/folder-permissions/", payload);
    f.reset();
    openPerms();
  }
  async function removePerm(id) {
    await api.delete(`/folder-permissions/${id}/`);
    openPerms();
  }

  return (
    <div className="grid-2" style={{ gridTemplateColumns: "320px 1fr" }}>
      <div className="card">
        <div className="card-head"><h2>Folders</h2><span className="eyebrow">by control</span></div>
        <div className="card-body tree" style={{ maxHeight: "70vh", overflowY: "auto" }}>
          {tree.length === 0 ? <div className="empty">No folders yet.<br />Run seed_frameworks --with-folders.</div>
            : tree.map((n) => <TreeNode key={n.id} node={n} selected={folder?.id} onSelect={selectFolder} />)}
        </div>
      </div>

      <div className="card">
        {!folder ? (
          <div className="empty" style={{ padding: 60 }}>Select a folder to view its documents.</div>
        ) : (
          <>
            <div className="card-head">
              <div>
                <h2>{folder.name}</h2>
                <div className="eyebrow" style={{ marginTop: 3 }}>
                  access: {folder.my_access || "none"}{folder.control ? ` · control linked` : ""}
                </div>
              </div>
              {canManage && (
                <button className="btn small" onClick={() => (showPerms ? setShowPerms(false) : openPerms())}>
                  {showPerms ? "Hide access" : "Manage access"}
                </button>
              )}
            </div>

            <div className="card-body">
              {showPerms && (
                <div style={{ background: "#f7f9fb", border: "1px solid var(--line)", borderRadius: 10, padding: 14, marginBottom: 18 }}>
                  <div className="eyebrow" style={{ marginBottom: 10 }}>Folder access (inherited by subfolders)</div>
                  <table>
                    <tbody>
                      {perms.map((p) => (
                        <tr key={p.id}>
                          <td>{p.role_name || p.user_name}</td>
                          <td><span className="badge neutral">{p.access_level}</span></td>
                          <td style={{ textAlign: "right" }}>
                            <button className="btn small" onClick={() => removePerm(p.id)}>Remove</button>
                          </td>
                        </tr>
                      ))}
                      {perms.length === 0 && <tr><td colSpan={3} style={{ color: "var(--muted)" }}>No explicit grants.</td></tr>}
                    </tbody>
                  </table>
                  <form onSubmit={addPerm} style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <select name="role" style={{ flex: 2 }}>
                      <option value="">Grant role…</option>
                      {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                    <select name="level" style={{ flex: 1 }}>
                      <option value="view">View</option>
                      <option value="edit">Edit</option>
                      <option value="manage">Manage</option>
                    </select>
                    <button className="btn primary small">Grant</button>
                  </form>
                </div>
              )}

              {canEdit && (
                <form onSubmit={upload} style={{ display: "grid", gridTemplateColumns: "2fr 1.3fr 1.3fr auto", gap: 8, marginBottom: 18 }}>
                  <input name="name" placeholder="Document name" required />
                  <select name="cadence" defaultValue="annual">
                    {CADENCE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                  <select name="owner" defaultValue="">
                    <option value="">Owner (me)</option>
                    {users.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                  </select>
                  <input ref={uploadRef} type="file" name="file" required style={{ display: "none" }}
                         onChange={(e) => setFileName(e.target.files[0]?.name || "")} />
                  <button type="button" className="btn" onClick={() => uploadRef.current.click()}>
                    {fileName ? `✓ ${fileName.slice(0, 18)}` : "Choose file"}
                  </button>
                  <button className="btn primary" style={{ gridColumn: "1 / -1" }}>Upload document</button>
                </form>
              )}

              {docs.length === 0 ? (
                <div className="empty">No documents in this folder yet.</div>
              ) : (
                <table>
                  <thead>
                    <tr><th>Document</th><th style={{ width: 120 }}>Owner</th><th style={{ width: 120 }}>Next review</th><th style={{ width: 90 }}>Status</th><th style={{ width: 200 }}></th></tr>
                  </thead>
                  <tbody>
                    {docs.map((d) => (
                      <Fragment key={d.id}>
                        <tr>
                          <td>
                            <a href={d.file} target="_blank" rel="noreferrer" style={{ fontWeight: 500, color: "var(--accent-2)" }}>{d.name}</a>
                            <div style={{ fontSize: 12, color: "var(--muted)" }} className="mono">v{d.version}{d.control_id ? ` · ${d.control_id}` : ""}</div>
                            {d.satisfies?.length > 0 && (
                              <div title="Controls this document is linked to as evidence">
                                {d.satisfies.map((s) => (
                                  <span key={s.link_id} className="evi-chip"><b>{s.label}</b></span>
                                ))}
                              </div>
                            )}
                          </td>
                          <td style={{ color: d.owner_name ? "var(--ink)" : "var(--muted)" }}>{d.owner_name || "—"}</td>
                          <td className="mono">{d.next_review_date || "—"}</td>
                          <td>{reviewBadge(d.days_until_review)}</td>
                          <td>
                            {canEdit && (
                              <div className="row-actions">
                                <button className="btn small" onClick={() => toggleMap(d)}>{mapDoc === d.id ? "Close" : "Map"}</button>
                                <button className="btn small" onClick={() => rename(d)}>Rename</button>
                                <button className="btn small" onClick={() => markReviewed(d)}>Reviewed</button>
                                <label className="btn small" style={{ cursor: "pointer" }}>
                                  Version
                                  <input type="file" style={{ display: "none" }}
                                         onChange={(e) => e.target.files[0] && newVersion(d, e.target.files[0])} />
                                </label>
                              </div>
                            )}
                          </td>
                        </tr>
                        {mapDoc === d.id && (
                          <tr>
                            <td colSpan={5} style={{ background: "#f7f9fb" }}>
                              <div style={{ padding: "6px 4px" }}>
                                <div className="eyebrow" style={{ marginBottom: 6 }}>Satisfies controls</div>
                                <div>
                                  {d.satisfies?.length === 0 && (
                                    <span style={{ color: "var(--muted)", fontSize: 12.5 }}>Not linked to any control yet.</span>
                                  )}
                                  {d.satisfies?.map((s) => (
                                    <span key={s.link_id} className="evi-chip">
                                      <b>{s.label}</b> {s.title.length > 36 ? s.title.slice(0, 36) + "…" : s.title}
                                      <span className="x" title="Unlink" onClick={() => removeLink(s.link_id)}>×</span>
                                    </span>
                                  ))}
                                </div>
                                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                                  <select defaultValue="" style={{ flex: 1 }}
                                          onChange={(e) => { addLink(d, e.target.value); e.target.value = ""; }}>
                                    <option value="">Link a control…</option>
                                    {controlChoices
                                      .filter((c) => !d.satisfies?.some((s) => s.control === c.id))
                                      .map((c) => (
                                        <option key={c.id} value={c.id}>
                                          {c.framework_name} · {c.label} — {c.title}
                                        </option>
                                      ))}
                                  </select>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
