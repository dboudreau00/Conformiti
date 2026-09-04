import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { FileUpIcon, FolderPlusIcon, KeyRoundIcon, Link2Icon, Trash2Icon, UploadIcon, XIcon } from "lucide-react";
import api, { fetchAll } from "../api/client.js";
import { Badge, Dot } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { SegmentedControl } from "../components/ui/SegmentedControl.jsx";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { FolderTree } from "../components/documents/FolderTree.jsx";
import { cn } from "../utils/cn.js";
import { errorText } from "../utils/a11y.js";
import { DOC_STATUS, dueLabel, dueTone, toneVar } from "../utils/tone.js";

const CADENCE = [
  ["none", "No review"], ["monthly", "Monthly"], ["quarterly", "Quarterly"],
  ["semiannual", "Every 6 months"], ["annual", "Annual"], ["biennial", "Every 2 years"],
];
const LEVELS = [["view", "View"], ["edit", "Edit"], ["manage", "Manage"]];
const ACCESS_TONE = { manage: "accent", edit: "info", view: "muted" };
const GRANT_BY = [{ id: "role", label: "Role" }, { id: "user", label: "User" }];
const EMPTY_UPLOAD = { name: "", cadence: "annual", owner: "", file: null };
const MAX_CHIPS = 3;

const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : DATE_FMT.format(d);
}

function findNode(nodes, id) {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findNode(n.children || [], id);
    if (hit) return hit;
  }
  return null;
}

// --- Row editors --------------------------------------------------------------

function MapEditor({ doc, choices, busy, onAdd, onRemove }) {
  const linked = new Set((doc.satisfies || []).map((s) => s.control));
  const options = (choices || []).filter((c) => !linked.has(c.id));
  const selectId = `map-control-${doc.id}`;
  return (
    <div className="border-t border-line bg-surface-2 px-5 py-3">
      <Label className="mb-2 block">Satisfies controls</Label>
      <div className="flex flex-wrap gap-1.5">
        {doc.satisfies?.length ? (
          doc.satisfies.map((s) => (
            <span
              key={s.link_id}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-accent/10 py-0.5 pl-2 pr-1 text-2xs font-medium text-accent ring-1 ring-accent/25"
            >
              <span className="font-mono">{s.label}</span>
              <span className="max-w-[240px] truncate text-muted">{s.title}</span>
              <button
                type="button"
                aria-label={`Unlink ${s.label}`}
                title="Unlink"
                disabled={busy}
                onClick={() => onRemove(s.link_id)}
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-accent/70 transition-colors duration-150 ease-out hover:bg-accent/15 hover:text-accent disabled:opacity-50"
              >
                <XIcon className="h-3 w-3" strokeWidth={2.5} />
              </button>
            </span>
          ))
        ) : (
          <span className="text-xs text-faint">Not linked to any control yet.</span>
        )}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <label htmlFor={selectId} className="sr-only">Link a control</label>
        <select
          id={selectId}
          className="input input-sm max-w-lg"
          value=""
          disabled={busy || !choices}
          onChange={(e) => onAdd(e.target.value)}
        >
          <option value="">{choices ? "Link a control…" : "Loading controls…"}</option>
          {options.map((c) => (
            <option key={c.id} value={c.id}>
              {c.framework_name} · {c.label} — {c.title}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function RenameEditor({ doc, value, onChange, onSubmit, onCancel, busy }) {
  const id = `rename-${doc.id}`;
  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2 px-5 py-3">
      <label htmlFor={id} className="field-label mb-0 shrink-0">New name</label>
      <input id={id} className="input input-sm max-w-md" value={value} onChange={(e) => onChange(e.target.value)} autoFocus required />
      <Button size="sm" variant="primary" type="submit" disabled={busy || !value.trim()}>Save</Button>
      <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
    </form>
  );
}

function AccessEditor({ perms, roles, users, busy, grantBy, onGrantBy, grant, onGrantChange, onGrant, onRemove }) {
  const list = grantBy === "role" ? roles : users;
  return (
    <div id="folder-access" className="border-b border-line bg-surface-2 px-5 py-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <Label>Folder access · inherited by subfolders</Label>
        {perms ? <Label>{perms.length} {perms.length === 1 ? "grant" : "grants"}</Label> : null}
      </div>
      {perms === null ? (
        <Loading className="py-4" />
      ) : perms.length === 0 ? (
        <p className="text-xs text-faint">No explicit grants. Access here comes from parent folders and role capabilities.</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {perms.map((p) => {
            const who = p.role_name || p.user_name || p.username || "—";
            return (
              <li key={p.id} className="flex items-center gap-3 px-3 py-2">
                <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{who}</span>
                <Badge tone="faint" mono>{p.role ? "role" : "user"}</Badge>
                <Badge tone={ACCESS_TONE[p.access_level] || "muted"} mono>{p.access_level}</Badge>
                <Button size="sm" variant="ghost" onClick={() => onRemove(p.id)} disabled={busy} aria-label={`Remove ${p.access_level} access for ${who}`}>
                  Remove
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <form onSubmit={onGrant} className="mt-3 flex flex-wrap items-end gap-2">
        <div>
          <Label className="mb-1.5 block">Grant by</Label>
          <SegmentedControl options={GRANT_BY} value={grantBy} onChange={onGrantBy} layoutId="doc-grant-by" ariaLabel="Grant by" />
        </div>
        <div className="min-w-[200px] flex-1">
          <label htmlFor="grant-target" className="field-label">{grantBy === "role" ? "Role" : "User"}</label>
          <select id="grant-target" className="input input-sm" value={grant.target} onChange={(e) => onGrantChange({ ...grant, target: e.target.value })} disabled={busy}>
            <option value="">{!list ? "Loading…" : grantBy === "role" ? "Choose a role…" : "Choose a user…"}</option>
            {(list || []).map((x) => (
              <option key={x.id} value={x.id}>
                {grantBy === "role" ? x.name : x.full_name || x.username}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="grant-level" className="field-label">Level</label>
          <select id="grant-level" className="input input-sm" value={grant.level} onChange={(e) => onGrantChange({ ...grant, level: e.target.value })} disabled={busy}>
            {LEVELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <Button size="sm" variant="primary" type="submit" disabled={busy || !grant.target}>Grant</Button>
      </form>
    </div>
  );
}

// --- Page -----------------------------------------------------------------------

export default function Documents({ me }) {
  const [tree, setTree] = useState([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [expanded, setExpanded] = useState(() => new Set());
  const [folderId, setFolderId] = useState(null);
  const [docs, setDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text}
  const [busy, setBusy] = useState(false);

  // Pick-lists, fetched the first time they are needed (null = not loaded yet).
  const [users, setUsers] = useState(null);
  const [roles, setRoles] = useState(null);
  const [controlChoices, setControlChoices] = useState(null);

  const [showUpload, setShowUpload] = useState(false);
  const [upload, setUpload] = useState(EMPTY_UPLOAD);
  const [showPerms, setShowPerms] = useState(false);
  const [perms, setPerms] = useState(null);
  const [grantBy, setGrantBy] = useState("role");
  const [grant, setGrant] = useState({ target: "", level: "view" });
  const [editor, setEditor] = useState(null); // { id, mode: "map" | "rename" }
  const [renameValue, setRenameValue] = useState("");
  const [newFolder, setNewFolder] = useState("");

  const fileRef = useRef(null);
  const versionRef = useRef(null);
  const versionDoc = useRef(null);
  const docsReq = useRef(0);
  const expandedOnce = useRef(false);

  const folder = useMemo(() => findNode(tree, folderId), [tree, folderId]);
  const canEdit = !!folder && ["edit", "manage"].includes(folder.my_access);
  const canManage = !!folder && folder.my_access === "manage";
  const canDelete = canManage && !folder.is_seeded;

  // Every write goes through this so a rejected request becomes a visible
  // notice instead of an unhandled rejection and a dead button.
  async function run(fn, okText) {
    setMsg(null);
    setBusy(true);
    try {
      await fn();
      if (okText) setMsg({ ok: true, text: okText });
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function loadTree() {
    try {
      const r = await api.get("/folders/tree/");
      setTree(r.data);
      if (!expandedOnce.current) {
        expandedOnce.current = true;
        setExpanded(new Set(r.data.map((n) => n.id)));
      }
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't load the folder tree.") });
    } finally {
      setTreeLoading(false);
    }
  }
  useEffect(() => { loadTree(); }, []);

  // The document list is paginated; fetchAll follows `next` so a folder with
  // more than a page of documents is never silently truncated.
  async function loadDocs(id, { silent = false } = {}) {
    const req = ++docsReq.current;
    if (!silent) setDocsLoading(true);
    try {
      const rows = await fetchAll(`/documents/?folder=${id}`);
      if (req === docsReq.current) setDocs(rows);
    } catch (e) {
      if (req === docsReq.current) {
        setDocs([]);
        setMsg({ ok: false, text: errorText(e, "Couldn't load documents for that folder.") });
      }
    } finally {
      if (req === docsReq.current) setDocsLoading(false);
    }
  }

  function selectFolder(node) {
    if (node.id === folderId) return;
    setFolderId(node.id);
    setShowPerms(false);
    setPerms(null);
    setEditor(null);
    setShowUpload(false);
    setMsg(null);
    loadDocs(node.id);
  }
  const refreshDocs = () => { if (folderId != null) loadDocs(folderId, { silent: true }); };

  function toggleNode(id, open) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (open) next.add(id); else next.delete(id);
      return next;
    });
  }

  // --- lazy pick-lists ---------------------------------------------------------
  async function ensureUsers() {
    if (users) return;
    try { setUsers(await fetchAll("/users/")); }
    catch (e) { setMsg({ ok: false, text: errorText(e, "Couldn't load the user list.") }); }
  }
  async function ensureRoles() {
    if (roles) return;
    try { setRoles(await fetchAll("/roles/")); }
    catch (e) { setMsg({ ok: false, text: errorText(e, "Couldn't load the role list.") }); }
  }
  async function ensureControls() {
    if (controlChoices) return;
    try {
      const r = await api.get("/control-evidence/choices/");
      setControlChoices(r.data.controls || []);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't load the control catalogue.") });
    }
  }

  // --- upload --------------------------------------------------------------------
  function toggleUpload() {
    if (!canEdit) return;
    const next = !showUpload;
    setShowUpload(next);
    if (next) ensureUsers();
  }
  async function submitUpload(e) {
    e.preventDefault();
    if (!upload.file) { setMsg({ ok: false, text: "Choose a file first." }); return; }
    const fd = new FormData();
    fd.append("folder", folder.id);
    fd.append("name", upload.name.trim());
    fd.append("review_cadence", upload.cadence);
    if (upload.owner) fd.append("owner", upload.owner);
    fd.append("file", upload.file);
    const ok = await run(() => api.post("/documents/", fd), "Document uploaded.");
    if (ok) {
      setUpload(EMPTY_UPLOAD);
      if (fileRef.current) fileRef.current.value = "";
      setShowUpload(false);
      refreshDocs();
      loadTree();
    }
  }

  // --- document actions ---------------------------------------------------------
  function toggleMap(d) {
    if (editor?.id === d.id && editor.mode === "map") { setEditor(null); return; }
    setEditor({ id: d.id, mode: "map" });
    ensureControls();
  }
  async function addLink(d, controlId) {
    if (!controlId) return;
    await run(() => api.post("/control-evidence/", { control: Number(controlId), document: d.id }), "Control linked.");
    refreshDocs(); // always refresh: a duplicate or race is best resolved with server truth
  }
  async function removeLink(linkId) {
    const ok = await run(() => api.delete(`/control-evidence/${linkId}/`), "Control unlinked.");
    if (ok) refreshDocs();
  }

  function toggleRename(d) {
    if (editor?.id === d.id && editor.mode === "rename") { setEditor(null); return; }
    setEditor({ id: d.id, mode: "rename" });
    setRenameValue(d.name);
  }
  async function submitRename(e, d) {
    e.preventDefault();
    const name = renameValue.trim();
    if (!name) return;
    const ok = await run(() => api.post(`/documents/${d.id}/rename/`, { name }), "Document renamed.");
    if (ok) { setEditor(null); refreshDocs(); }
  }

  async function markReviewed(d) {
    const ok = await run(() => api.post(`/documents/${d.id}/mark_reviewed/`), "Marked as reviewed.");
    if (ok) refreshDocs();
  }

  function pickVersion(d) {
    versionDoc.current = d;
    versionRef.current?.click();
  }
  async function onVersionFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    const d = versionDoc.current;
    if (!file || !d) return;
    const fd = new FormData();
    fd.append("file", file);
    const ok = await run(() => api.post(`/documents/${d.id}/new_version/`, fd), "New version uploaded.");
    if (ok) refreshDocs();
  }

  // --- folder access --------------------------------------------------------------
  async function loadPerms(id) {
    try {
      const r = await api.get(`/folders/${id}/permissions/`);
      setPerms(r.data);
    } catch (e) {
      setPerms([]);
      setMsg({ ok: false, text: errorText(e, "Couldn't load folder access.") });
    }
  }
  function togglePerms() {
    const next = !showPerms;
    setShowPerms(next);
    if (next) {
      setPerms(null);
      loadPerms(folder.id);
      ensureRoles();
      ensureUsers();
    }
  }
  function changeGrantBy(id) {
    setGrantBy(id);
    setGrant((g) => ({ ...g, target: "" }));
  }
  async function submitGrant(e) {
    e.preventDefault();
    if (!grant.target) return;
    const payload = { folder: folder.id, access_level: grant.level };
    payload[grantBy === "role" ? "role" : "user"] = Number(grant.target);
    const ok = await run(() => api.post("/folder-permissions/", payload), "Access granted.");
    if (ok) { setGrant((g) => ({ ...g, target: "" })); loadPerms(folder.id); }
  }
  async function removeGrant(id) {
    const ok = await run(() => api.delete(`/folder-permissions/${id}/`), "Access removed.");
    if (ok) loadPerms(folder.id);
  }

  // --- folders ----------------------------------------------------------------------
  async function createFolder(e) {
    e.preventDefault();
    const name = newFolder.trim();
    if (!name) return;
    const parent = folder.id;
    const ok = await run(() => api.post("/folders/", { name, parent }), "Folder created.");
    if (ok) {
      setNewFolder("");
      toggleNode(parent, true);
      loadTree();
    }
  }
  async function deleteFolder() {
    if (!window.confirm(`Delete "${folder.name}" and everything inside it? This cannot be undone.`)) return;
    const id = folder.id;
    const ok = await run(() => api.delete(`/folders/${id}/`), "Folder deleted.");
    if (ok) {
      setFolderId(null);
      setDocs([]);
      setEditor(null);
      setShowPerms(false);
      setShowUpload(false);
      loadTree();
    }
  }

  // --- derived -----------------------------------------------------------------------
  const mix = useMemo(
    () => Object.entries(DOC_STATUS).map(([key, m]) => ({ key, ...m, count: docs.filter((d) => d.status === key).length })),
    [docs]
  );
  const cols = canEdit
    ? "minmax(220px, 1.5fr) 110px 130px 130px 64px minmax(150px, 1fr) auto"
    : "minmax(220px, 1.5fr) 110px 130px 130px 64px minmax(150px, 1fr)";
  const meName = me?.full_name || me?.username || "Me";

  return (
    <PanelTransition>
      <AnimatePresence initial={false}>
        {msg ? (
          <motion.div
            key={`${msg.ok}-${msg.text}`}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: EASE }}
            className="mb-4"
          >
            <div className={cn("notice flex items-start justify-between gap-3", msg.ok ? "notice-ok" : "notice-err")} role={msg.ok ? "status" : "alert"}>
              <span>{msg.text}</span>
              <button type="button" aria-label="Dismiss" onClick={() => setMsg(null)} className="shrink-0 opacity-70 transition-opacity hover:opacity-100">
                <XIcon className="h-3.5 w-3.5" />
              </button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <Stack className="grid grid-cols-12 gap-4">
        {/* ---------------- Left: folders + status mix ---------------- */}
        <StackItem className="col-span-12 lg:col-span-3">
          <Panel className="overflow-hidden">
            <PanelHeader title="Folders" meta="Visible to you" />
            {treeLoading ? (
              <Loading />
            ) : tree.length === 0 ? (
              <Empty title="No folders yet">
                Run <span className="font-mono">seed_frameworks --with-folders</span> to generate the evidence tree.
              </Empty>
            ) : (
              <FolderTree
                nodes={tree}
                selectedId={folderId}
                expanded={expanded}
                onToggle={toggleNode}
                onSelect={selectFolder}
                className="max-h-[60vh] overflow-y-auto"
              />
            )}
            <div className="border-t border-line p-3">
              <Button
                size="sm"
                variant="primary"
                className="w-full"
                icon={<UploadIcon className="h-3.5 w-3.5" strokeWidth={2} />}
                disabled={!canEdit || busy}
                aria-expanded={showUpload}
                aria-controls={showUpload ? "doc-upload-form" : undefined}
                onClick={toggleUpload}
              >
                Upload document
              </Button>
              {!canEdit ? (
                <p className="mt-2 text-center text-2xs text-faint">
                  {folder ? "This folder is view-only for you." : "Select a folder you can edit."}
                </p>
              ) : null}
              <AnimatePresence initial={false}>
                {showUpload && canEdit ? (
                  <Collapse key="upload" open>
                    <form id="doc-upload-form" onSubmit={submitUpload} className="mt-3 space-y-3 rounded-lg border border-line bg-surface-2 p-3">
                      <Label className="block truncate">Upload into {folder.name}</Label>
                      <div>
                        <label htmlFor="upload-name" className="field-label">Document name</label>
                        <input
                          id="upload-name"
                          className="input input-sm"
                          placeholder="e.g. Access Control Policy"
                          value={upload.name}
                          onChange={(e) => setUpload((u) => ({ ...u, name: e.target.value }))}
                          required
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label htmlFor="upload-cadence" className="field-label">Review cadence</label>
                          <select id="upload-cadence" className="input input-sm" value={upload.cadence} onChange={(e) => setUpload((u) => ({ ...u, cadence: e.target.value }))}>
                            {CADENCE.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                          </select>
                        </div>
                        <div>
                          <label htmlFor="upload-owner" className="field-label">Owner</label>
                          <select id="upload-owner" className="input input-sm" value={upload.owner} onChange={(e) => setUpload((u) => ({ ...u, owner: e.target.value }))}>
                            <option value="">{meName} (me)</option>
                            {(users || []).filter((u) => u.id !== me?.id).map((u) => (
                              <option key={u.id} value={u.id}>{u.full_name || u.username}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                      <div>
                        <input
                          ref={fileRef}
                          id="upload-file"
                          type="file"
                          className="sr-only"
                          aria-label="Document file"
                          onChange={(e) => setUpload((u) => ({ ...u, file: e.target.files?.[0] || null }))}
                        />
                        <Button
                          size="sm"
                          className="w-full justify-start"
                          icon={<FileUpIcon className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />}
                          onClick={() => fileRef.current?.click()}
                          disabled={busy}
                        >
                          <span className={cn("truncate", !upload.file && "text-muted")}>{upload.file ? upload.file.name : "Choose file…"}</span>
                        </Button>
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="primary" type="submit" className="flex-1" disabled={busy || !upload.name.trim() || !upload.file}>
                          {busy ? "Uploading…" : "Upload"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setShowUpload(false)} disabled={busy}>Cancel</Button>
                      </div>
                    </form>
                  </Collapse>
                ) : null}
              </AnimatePresence>
            </div>
          </Panel>

          <Panel className="mt-4 p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <Label>Status mix</Label>
              <Label className="truncate">{folder ? folder.name : "no folder"}</Label>
            </div>
            <ul className="space-y-2">
              {mix.map((m) => (
                <li key={m.key} className="flex items-center gap-2">
                  <Dot tone={m.tone} />
                  <span className="flex-1 text-xs text-muted">{m.label}</span>
                  <span className="tabular font-mono text-2xs text-ink">{m.count}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </StackItem>

        {/* ---------------- Right: documents in the selected folder ---------------- */}
        <StackItem className="col-span-12 lg:col-span-9">
          <Panel className="overflow-hidden">
            {!folder ? (
              <Empty title="Select a folder" className="py-20">Pick a folder on the left to see its documents.</Empty>
            ) : (
              <>
                <PanelHeader title={folder.name}>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <Label>{docs.length} {docs.length === 1 ? "document" : "documents"}</Label>
                    <Badge tone={ACCESS_TONE[folder.my_access] || "faint"} mono>{folder.my_access || "no access"}</Badge>
                    {folder.is_seeded ? <Badge tone="faint" mono>framework</Badge> : null}
                    {canManage ? (
                      <Button
                        size="sm"
                        icon={<KeyRoundIcon className="h-3.5 w-3.5" strokeWidth={2} />}
                        aria-expanded={showPerms}
                        aria-controls={showPerms ? "folder-access" : undefined}
                        onClick={togglePerms}
                        disabled={busy}
                      >
                        {showPerms ? "Hide access" : "Manage access"}
                      </Button>
                    ) : null}
                    {canDelete ? (
                      <Button size="sm" variant="danger" icon={<Trash2Icon className="h-3.5 w-3.5" strokeWidth={2} />} onClick={deleteFolder} disabled={busy}>
                        Delete folder
                      </Button>
                    ) : null}
                  </div>
                </PanelHeader>

                <AnimatePresence initial={false}>
                  {showPerms && canManage ? (
                    <Collapse key="perms" open>
                      <AccessEditor
                        perms={perms}
                        roles={roles}
                        users={users}
                        busy={busy}
                        grantBy={grantBy}
                        onGrantBy={changeGrantBy}
                        grant={grant}
                        onGrantChange={setGrant}
                        onGrant={submitGrant}
                        onRemove={removeGrant}
                      />
                    </Collapse>
                  ) : null}
                </AnimatePresence>

                <div className="overflow-x-auto">
                  <div className="min-w-[880px]">
                    <div className="grid gap-4 border-b border-line bg-surface-2 px-5 py-2" style={{ gridTemplateColumns: cols }}>
                      <Label>Document</Label>
                      <Label>Status</Label>
                      <Label>Review due</Label>
                      <Label>Owner</Label>
                      <Label>Version</Label>
                      <Label>Controls</Label>
                      {canEdit ? <Label className="text-right">Actions</Label> : null}
                    </div>
                    {docsLoading ? (
                      <Loading />
                    ) : docs.length === 0 ? (
                      <Empty title="No documents in this folder">
                        {canEdit ? "Use Upload document to add the first one." : "Nothing has been uploaded here yet."}
                      </Empty>
                    ) : (
                      <ul className="divide-y divide-line">
                        <AnimatePresence>
                          {docs.map((d, i) => {
                            const days = d.days_until_review;
                            const status = DOC_STATUS[d.status] || { label: d.status, tone: "muted" };
                            const mode = editor?.id === d.id ? editor.mode : null;
                            const chips = d.satisfies || [];
                            return (
                              <motion.li
                                key={d.id}
                                initial={{ opacity: 0, y: 6 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0 }}
                                transition={{ duration: 0.2, ease: EASE, delay: Math.min(i, 12) * 0.02 }}
                              >
                                <div
                                  className="grid items-center gap-4 px-5 py-3 transition-colors duration-150 ease-out hover:bg-surface-2"
                                  style={{ gridTemplateColumns: cols }}
                                >
                                  <span className="min-w-0">
                                    <a
                                      href={d.file || undefined}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="block truncate text-[13px] font-medium text-ink transition-colors duration-150 ease-out hover:text-accent"
                                    >
                                      {d.name}
                                    </a>
                                    <span className="block truncate font-mono text-2xs uppercase tracking-label text-faint">
                                      {d.folder_path}{d.control_id ? ` · ${d.control_id}` : ""}
                                    </span>
                                  </span>
                                  <span>
                                    <Badge tone={status.tone} dot>{status.label}</Badge>
                                  </span>
                                  <span className="flex flex-col items-start gap-1">
                                    <span className="tabular font-mono text-xs" style={{ color: toneVar(dueTone(days)) }}>
                                      {fmtDate(d.next_review_date)}
                                    </span>
                                    <Badge tone={dueTone(days)} mono>{dueLabel(days)}</Badge>
                                  </span>
                                  <span className={cn("truncate text-xs", d.owner_name ? "text-muted" : "text-faint")}>{d.owner_name || "—"}</span>
                                  <span className="tabular font-mono text-xs text-muted">v{d.version}</span>
                                  <span className="flex flex-wrap gap-1" title={chips.length ? "Controls this document is linked to as evidence" : undefined}>
                                    {chips.length === 0 ? <span className="text-2xs text-faint">—</span> : null}
                                    {chips.slice(0, MAX_CHIPS).map((s) => (
                                      <Badge key={s.link_id} tone="accent" mono title={s.title}>{s.label}</Badge>
                                    ))}
                                    {chips.length > MAX_CHIPS ? <Badge tone="muted" mono>+{chips.length - MAX_CHIPS}</Badge> : null}
                                  </span>
                                  {canEdit ? (
                                    <span className="flex items-center justify-end gap-1">
                                      <Button
                                        size="sm"
                                        variant={mode === "map" ? "secondary" : "ghost"}
                                        icon={<Link2Icon className="h-3.5 w-3.5" strokeWidth={2} />}
                                        aria-expanded={mode === "map"}
                                        onClick={() => toggleMap(d)}
                                        disabled={busy}
                                      >
                                        Map
                                      </Button>
                                      <Button size="sm" variant={mode === "rename" ? "secondary" : "ghost"} aria-expanded={mode === "rename"} onClick={() => toggleRename(d)} disabled={busy}>
                                        Rename
                                      </Button>
                                      <Button size="sm" variant="ghost" onClick={() => markReviewed(d)} disabled={busy}>Reviewed</Button>
                                      <Button size="sm" variant="ghost" onClick={() => pickVersion(d)} disabled={busy}>Version</Button>
                                    </span>
                                  ) : null}
                                </div>
                                <AnimatePresence initial={false}>
                                  {mode === "map" ? (
                                    <Collapse key="map" open>
                                      <MapEditor doc={d} choices={controlChoices} busy={busy} onAdd={(id) => addLink(d, id)} onRemove={removeLink} />
                                    </Collapse>
                                  ) : mode === "rename" ? (
                                    <Collapse key="rename" open>
                                      <RenameEditor
                                        doc={d}
                                        value={renameValue}
                                        onChange={setRenameValue}
                                        onSubmit={(e) => submitRename(e, d)}
                                        onCancel={() => setEditor(null)}
                                        busy={busy}
                                      />
                                    </Collapse>
                                  ) : null}
                                </AnimatePresence>
                              </motion.li>
                            );
                          })}
                        </AnimatePresence>
                      </ul>
                    )}
                  </div>
                </div>

                {canEdit ? (
                  <form onSubmit={createFolder} className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2 px-5 py-3">
                    <FolderPlusIcon className="h-4 w-4 shrink-0 text-faint" strokeWidth={1.75} aria-hidden="true" />
                    <label htmlFor="new-subfolder" className="sr-only">New subfolder name</label>
                    <input
                      id="new-subfolder"
                      className="input input-sm max-w-xs"
                      placeholder={`New subfolder in ${folder.name}`}
                      value={newFolder}
                      onChange={(e) => setNewFolder(e.target.value)}
                      disabled={busy}
                    />
                    <Button size="sm" type="submit" disabled={busy || !newFolder.trim()}>Create subfolder</Button>
                  </form>
                ) : null}
              </>
            )}
          </Panel>
        </StackItem>
      </Stack>

      {/* Single hidden picker for "Version": the row button records which document, then opens it. */}
      <input
        ref={versionRef}
        type="file"
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        aria-label="New version file"
        onChange={onVersionFile}
      />
    </PanelTransition>
  );
}
