import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { DownloadIcon, FileUpIcon, FolderPlusIcon, KeyRoundIcon, MoreHorizontalIcon, SearchIcon, Trash2Icon, UploadIcon, XIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import DocumentViewer, { documentViewerProps } from "../components/documents/DocumentViewer.jsx";
import { ControlPicker } from "../components/controls/ControlPicker.jsx";
import { Badge, Dot } from "../components/ui/Badge.jsx";
import { Button, IconButton } from "../components/ui/Button.jsx";
import { useConfirm } from "../components/ui/Dialog.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { SegmentedControl } from "../components/ui/SegmentedControl.jsx";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { FolderTree } from "../components/documents/FolderTree.jsx";
import { cn } from "../utils/cn.js";
import { errorText, loadFailReason as failReason } from "../utils/a11y.js";
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
// Mirrors Document.CADENCE_MONTHS on the server, for the Mark reviewed
// confirmation: a cadence missing here schedules no next review at all.
const CADENCE_MONTHS = { monthly: 1, quarterly: 3, semiannual: 6, annual: 12, biennial: 24 };

// Table columns. The grid template and the scroll wrapper's min-width both
// come from the same numbers: a wrapper narrower than its tracks let the
// header band and the row dividers stop short of the last column whenever
// the table scrolled sideways. With the actions column the document table
// needs 756px, inside the roughly 785px panel a 1366 by 768 laptop leaves.
const COL_GAP = 12; // gap-3 on the header and every row
const ROW_PAD = 40; // px-5, both sides
const track = (px, fr) => [fr ? `minmax(${px}px, ${fr}fr)` : `${px}px`, px];
function columns(tracks) {
  return {
    template: tracks.map(([t]) => t).join(" "),
    minWidth: tracks.reduce((n, [, px]) => n + px, 0) + COL_GAP * (tracks.length - 1) + ROW_PAD,
  };
}
const DOC_TRACKS = [
  track(176, 1.6), // document name and its download button
  track(100), // status, with room for the quarantined badge under it
  track(92), // review due
  track(80, 1), // owner
  track(56), // version
  track(112, 1), // controls
];
const DOC_COLS = columns(DOC_TRACKS);
const DOC_COLS_EDIT = columns([...DOC_TRACKS, track(28)]); // plus one IconButton
const SEARCH_COLS = columns([track(176, 1.6), track(140, 1), track(100), track(92), track(80, 1)]);

function fmtDate(iso) {
  if (!iso) return "-";
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

// Why a read failed, for LoadError to show, comes from utils/a11y.js
// (loadFailReason): a folder deleted meanwhile is a 400 that a retry only
// repeats, and its own words say so.

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
      <div className="mt-3 max-w-lg">
        <ControlPicker
          id={selectId}
          label="Link a control"
          placeholder="Link a control by reference or title"
          controls={choices ? options : null}
          disabled={busy}
          onPick={(c) => onAdd(String(c.id))}
        />
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

// Per document: the menu that is closing is still in the page for the length
// of its exit while the next row's opens.
const menuId = (doc) => `doc-actions-${doc.id}`;

/** Trigger for the per-row actions menu. The menu itself renders at the page
 * root (see DocActionsMenu below): the row lives inside an overflow-x-auto
 * table and a framer-motion element with its own transform, either of which
 * would clip or mis-place a popover nested directly inside the row. Enter,
 * Space and ArrowDown open it on its first item, ArrowUp on its last. On a
 * menu that is already open the arrow keys move focus into it instead. */
function RowActionsTrigger({ doc, open, busy, onToggle }) {
  return (
    <IconButton
      label={`Actions for ${doc.name}`}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId(doc) : undefined}
      disabled={busy}
      data-actions-trigger="true"
      onClick={(e) => onToggle(doc, e.currentTarget)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        onToggle(doc, e.currentTarget, e.key === "ArrowUp" ? "last" : "first", true);
      }}
    >
      <MoreHorizontalIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
    </IconButton>
  );
}

const MENU_GAP = 6; // between the trigger and the menu
const MENU_EDGE = 8; // the least room kept between the menu and the viewport edge

/** Map, Rename, Mark reviewed and Upload new version behind one menu button,
 * so the row's last column stays one button wide at laptop width (the four
 * as inline buttons need about 260px, a third of the panel).
 *
 * A menu in the WAI-ARIA sense, because it is the only way to reach those
 * four: focus moves to an item on open, ArrowUp and ArrowDown (wrapping),
 * Home and End move between items, Enter and Space activate one, and Escape
 * or Tab closes it and puts focus back on the trigger. Choosing an item does
 * the same before the action runs, so a dialog it opens hands focus back to
 * the trigger rather than to an item that has since unmounted.
 *
 * Positioned from the trigger's own rect, and re-positioned whenever the page
 * or the table scrolls, the window resizes or the page grows or shrinks, so
 * it stays with its row. It opens upwards when there is no room below, which
 * is where the last rows of a long folder are. */
function DocActionsMenu({ doc, trigger, focusAt, openRequest, mapOpen, renameOpen, onMap, onRename, onMarkReviewed, onNewVersion, onClose }) {
  const ref = useRef(null);

  // Placed by writing to the node, not through state, so it is in place
  // before the first paint and before focus moves into it.
  useLayoutEffect(() => {
    function place() {
      const el = ref.current;
      if (!el) return;
      if (!trigger.isConnected) { onClose(); return; }
      const r = trigger.getBoundingClientRect();
      const vw = document.documentElement.clientWidth;
      const vh = document.documentElement.clientHeight;
      const h = el.offsetHeight;
      const below = vh - r.bottom - MENU_GAP - MENU_EDGE;
      const above = r.top - MENU_GAP - MENU_EDGE;
      const up = h > below && above > below;
      el.style.top = `${up ? r.top - MENU_GAP - h : r.bottom + MENU_GAP}px`;
      el.style.left = `${Math.max(MENU_EDGE, Math.min(r.right - el.offsetWidth, vw - MENU_EDGE - el.offsetWidth))}px`;
      el.style.transformOrigin = up ? "bottom right" : "top right";
    }
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    // A notice arriving above the table moves the row without any scroll.
    const grown = new ResizeObserver(place);
    grown.observe(document.body);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      grown.disconnect();
    };
  }, [trigger, onClose]);

  useLayoutEffect(() => {
    const items = ref.current?.querySelectorAll('[role="menuitem"]') || [];
    items[focusAt === "last" ? items.length - 1 : 0]?.focus({ preventScroll: true });
    // Focus moves in on every request to open, not once per mount: a menu
    // reopened for the same document inside its exit is the same instance
    // brought back by AnimatePresence, and the trigger's arrow keys on an open
    // menu mount nothing either.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRequest]);

  useEffect(() => {
    const onDown = (e) => {
      if (ref.current && ref.current.contains(e.target)) return;
      if (e.target.closest?.("[data-actions-trigger]")) return;
      onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  function backToTrigger() {
    onClose();
    trigger.focus();
  }
  function pick(fn) {
    backToTrigger();
    fn();
  }
  function onKeyDown(e) {
    const items = Array.from(ref.current?.querySelectorAll('[role="menuitem"]') || []);
    const at = items.indexOf(document.activeElement);
    const go = (i) => { e.preventDefault(); items[(i + items.length) % items.length]?.focus(); };
    switch (e.key) {
      case "ArrowDown": go(at + 1); break;
      case "ArrowUp": go(at < 0 ? items.length - 1 : at - 1); break;
      case "Home": go(0); break;
      case "End": go(items.length - 1); break;
      case "Escape":
      case "Tab":
        e.preventDefault();
        e.stopPropagation();
        backToTrigger();
        break;
      default:
    }
  }

  const item = (label, fn, on = false) => (
    <li role="none">
      <button
        type="button"
        role="menuitem"
        tabIndex={-1}
        onClick={() => pick(fn)}
        className={cn(
          "block w-full rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors duration-150 ease-out",
          on ? "bg-accent/10 text-accent" : "text-ink hover:bg-surface-2"
        )}
      >
        {label}
      </button>
    </li>
  );

  return (
    <motion.div
      ref={ref}
      id={menuId(doc)}
      role="menu"
      aria-label={`Actions for ${doc.name}`}
      onKeyDown={onKeyDown}
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -4, scale: 0.98 }}
      transition={{ duration: 0.16, ease: EASE }}
      style={{ position: "fixed", zIndex: 50 }}
      className="w-[200px] overflow-hidden rounded-xl border border-line bg-surface shadow-pop"
    >
      <ul role="none" className="p-1.5">
        {/* Map and Rename open an editor under the row; choosing one again
            closes it, and the label says so rather than a pressed state,
            which a menu item cannot carry. */}
        {item(mapOpen ? "Close control mapping" : "Map to controls", onMap, mapOpen)}
        {item(renameOpen ? "Cancel rename" : "Rename", onRename, renameOpen)}
        {item("Mark reviewed", onMarkReviewed)}
        {item("Upload new version", onNewVersion)}
      </ul>
    </motion.div>
  );
}

function AccessEditor({ perms, permsErr, onRetry, roles, users, busy, grantBy, onGrantBy, grant, onGrantChange, onGrant, onRemove }) {
  const list = grantBy === "role" ? roles : users;
  return (
    <div id="folder-access" className="border-b border-line bg-surface-2 px-5 py-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <Label>Folder access · inherited by subfolders</Label>
        {permsErr ? <Label>- grants</Label> : perms ? <Label>{perms.length} {perms.length === 1 ? "grant" : "grants"}</Label> : null}
      </div>
      {permsErr ? (
        <LoadError what="Folder access" reason={permsErr.reason} onRetry={onRetry} className="py-4" />
      ) : perms === null ? (
        <Loading className="py-4" />
      ) : perms.length === 0 ? (
        <p className="text-xs text-faint">No explicit grants. Access here comes from parent folders and role capabilities.</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {perms.map((p) => {
            const who = p.role_name || p.user_name || p.username || "-";
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
  // A failed read is { reason } (see failReason), never an empty list: a tree
  // that did not load read as "No folders yet" and offered to make the first.
  const [treeErr, setTreeErr] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [folderId, setFolderId] = useState(null);
  const [docs, setDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsErr, setDocsErr] = useState(null);
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
  const [permsErr, setPermsErr] = useState(null);
  const [grantBy, setGrantBy] = useState("role");
  const [grant, setGrant] = useState({ target: "", level: "view" });
  const [editor, setEditor] = useState(null); // { id, mode: "map" | "rename" }
  const [renameValue, setRenameValue] = useState("");
  const [newFolder, setNewFolder] = useState("");
  const [viewing, setViewing] = useState(null); // props for the in-browser viewer
  const [actionsFor, setActionsFor] = useState(null); // { doc, trigger, focusAt: "first" | "last", openRequest }

  const fileRef = useRef(null);
  const versionRef = useRef(null);
  const versionDoc = useRef(null);
  const docsReq = useRef(0);
  const menuRequests = useRef(0);
  const expandedOnce = useRef(false);

  const folder = useMemo(() => findNode(tree, folderId), [tree, folderId]);
  const canEdit = !!folder && ["edit", "manage"].includes(folder.my_access);
  // Making a folder at the root is not granted by a folder, because there is
  // no folder to grant it: it takes the workspace-wide capability.
  const canManageFolders = !!me?.capabilities?.manage_folders || !!me?.is_superuser;
  const { ask, confirmDialog } = useConfirm();
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
      setTreeErr(null);
      if (!expandedOnce.current) {
        expandedOnce.current = true;
        setExpanded(new Set(r.data.map((n) => n.id)));
      }
    } catch (e) {
      // A refresh after a change that fails leaves the tree on screen, which
      // is still right apart from that change, so a notice says so. A first
      // load that fails has no tree at all, and says that in its place.
      if (expandedOnce.current) setMsg({ ok: false, text: errorText(e, "Couldn't load the folder tree.") });
      else setTreeErr({ reason: failReason(e) });
    } finally {
      setTreeLoading(false);
    }
  }
  useEffect(() => { loadTree(); }, []);
  function retryTree() {
    setTreeErr(null);
    setTreeLoading(true);
    loadTree();
  }

  // The document list is paginated; fetchAll follows `next` so a folder with
  // more than a page of documents is never silently truncated.
  async function loadDocs(id, { silent = false } = {}) {
    const req = ++docsReq.current;
    if (!silent) setDocsLoading(true);
    setDocsErr(null);
    try {
      const rows = await fetchAll(`/documents/?folder=${id}`);
      if (req === docsReq.current) setDocs(rows);
    } catch (e) {
      if (req === docsReq.current) {
        setDocs([]);
        setDocsErr({ reason: failReason(e) });
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
    setActionsFor(null);
    loadDocs(node.id);
  }
  /** `openOnly` is the trigger's arrow keys, which open the menu and never
   * close it. Every open carries a fresh `openRequest`, which is what moves
   * focus into the menu, so it does even when no new menu mounts. */
  function toggleActions(doc, trigger, focusAt = "first", openOnly = false) {
    const openRequest = ++menuRequests.current;
    setActionsFor((cur) => (cur?.doc.id === doc.id && !openOnly ? null : { doc, trigger, focusAt, openRequest }));
  }
  // Stable, because the menu re-binds its listeners whenever it changes.
  const closeActions = useCallback(() => setActionsFor(null), []);
  const refreshDocs = () => { if (folderId != null) loadDocs(folderId, { silent: true }); };

  // Search across every folder the person can see. Until 0.9.5 finding a
  // document meant knowing which of a hundred seeded folders it was in; the
  // API had ?search= all along and nothing on the page used it. Two letters
  // start it, a short pause between keystrokes, and the newest answer wins.
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState(null); // null = not searching
  const [searching, setSearching] = useState(false);
  // A search that failed is not one that found nothing: "0 matches, try a
  // shorter word" sent the reader off to retype a name that does exist.
  const [searchErr, setSearchErr] = useState(null);
  const [searchTry, setSearchTry] = useState(0);
  const searchReq = useRef(0);
  useEffect(() => {
    const q = query.trim();
    setSearchErr(null);
    if (q.length < 2) {
      searchReq.current += 1;
      setHits(null);
      setSearching(false);
      return undefined;
    }
    const req = ++searchReq.current;
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const rows = await fetchAll(`/documents/?search=${encodeURIComponent(q)}&ordering=name`);
        if (req === searchReq.current) setHits(rows);
      } catch (e) {
        if (req === searchReq.current) {
          setHits([]);
          setSearchErr({ reason: failReason(e) });
        }
      } finally {
        if (req === searchReq.current) setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query, searchTry]);

  // Open a hit's folder: expand the path down to it and select it.
  function jumpTo(doc) {
    const node = findNode(tree, doc.folder);
    if (!node) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      const walk = (nodes, trail) => {
        for (const n of nodes) {
          if (n.id === doc.folder) { trail.forEach((id) => next.add(id)); return true; }
          if (n.children?.length && walk(n.children, [...trail, n.id])) return true;
        }
        return false;
      };
      walk(tree, []);
      return next;
    });
    setQuery("");
    selectFolder(node);
  }

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

  // Runs inside the confirmation dialog, so a failure has to throw: the dialog
  // then stays open and says why. Through run() it was swallowed, and the
  // dialog closed as if the review had been recorded.
  async function markReviewed(d) {
    setMsg(null);
    setBusy(true);
    try {
      await api.post(`/documents/${d.id}/mark_reviewed/`);
    } catch (e) {
      throw new Error(errorText(e, "The review could not be recorded."));
    } finally {
      setBusy(false);
    }
    setMsg({ ok: true, text: "Marked as reviewed." });
    refreshDocs();
  }
  // Says everything the server does: it also approves the document whatever
  // its status was. The only way off Approved on this page is Upload new
  // version, which always lands on Draft, so a Draft can go back and an In
  // review or Expired document cannot.
  function confirmMarkReviewed(d) {
    const months = CADENCE_MONTHS[d.review_cadence];
    const from = DOC_STATUS[d.status]?.label || d.status;
    ask({
      title: `Mark ${d.name} reviewed?`,
      description: [
        "Today becomes the review date.",
        months
          ? `The next review falls due in ${months} ${months === 1 ? "month" : "months"}.`
          : "It has no review cadence, so no next review is scheduled.",
        d.status === "approved"
          ? null
          : d.status === "draft"
            ? "Its status changes from Draft to Approved. On this page, only Upload new version returns it to Draft."
            : `Its status changes from ${from} to Approved, and nothing on this page sets it back to ${from}.`,
        "This is written to the audit trail.",
      ].filter(Boolean).join(" "),
      confirmLabel: "Mark reviewed",
      tone: "primary",
      onConfirm: () => markReviewed(d),
    });
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
    setPermsErr(null);
    try {
      const r = await api.get(`/folders/${id}/permissions/`);
      setPerms(r.data);
    } catch (e) {
      setPermsErr({ reason: failReason(e) });
    }
  }
  function togglePerms() {
    const next = !showPerms;
    setShowPerms(next);
    if (next) {
      setPerms(null);
      setPermsErr(null);
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
  /** `parent` null makes a folder at the root, which is how the first one is made. */
  async function createFolder(e, parentId) {
    e.preventDefault();
    const name = newFolder.trim();
    if (!name) return;
    const parent = parentId === undefined ? folder.id : parentId;
    const ok = await run(() => api.post("/folders/", { name, parent }), "Folder created.");
    if (ok) {
      setNewFolder("");
      if (parent !== null) toggleNode(parent, true);
      loadTree();
    }
  }
  function deleteFolder() {
    ask({
      title: `Delete "${folder.name}"?`,
      description: "Everything inside it goes too: subfolders, documents and every version of them. This cannot be undone.",
      confirmLabel: "Delete the folder",
      onConfirm: () => reallyDeleteFolder(),
    });
  }
  async function reallyDeleteFolder() {
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
  // The counts describe the selected folder's list only once it has arrived.
  // Before that, or when it failed, they show a dash, not a confident zero
  // (or, mid-load, the previous folder's numbers under this folder's name).
  const countsKnown = !!folder && !docsLoading && !docsErr;
  const cols = canEdit ? DOC_COLS_EDIT : DOC_COLS;
  const meName = me?.full_name || me?.username || "Me";

  return (
    <PanelTransition>
      {confirmDialog}
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
            ) : treeErr ? (
              <LoadError what="The folder list" reason={treeErr.reason} onRetry={retryTree} />
            ) : tree.length === 0 ? (
              <Empty
                title="No folders yet"
                action={canManageFolders ? (
                  <form onSubmit={(e) => createFolder(e, null)} className="flex items-center gap-2">
                    <input
                      className="input input-sm max-w-[200px]"
                      placeholder="First folder name"
                      aria-label="First folder name"
                      value={newFolder}
                      onChange={(e) => setNewFolder(e.target.value)}
                      disabled={busy}
                    />
                    <Button size="sm" variant="primary" type="submit" disabled={busy || !newFolder.trim()}>
                      Create folder
                    </Button>
                  </form>
                ) : null}
              >
                {canManageFolders
                  ? "Make the first folder here, or load a framework library, which brings its evidence folders with it."
                  : "Ask an administrator to create the first folder, or to load a framework library, which brings its evidence folders with it."}
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
            {/* Upload lives in the folder's header now, so a folder the reader
                can edit leaves nothing to say here. */}
            {treeErr || canEdit ? null : (
              <div className="border-t border-line p-3">
                <p className="text-center text-2xs text-faint">
                  {!folder ? "Select a folder to upload" : "This folder is view-only for you."}
                </p>
              </div>
            )}
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
                  <span className="tabular font-mono text-2xs text-ink">{countsKnown ? m.count : "-"}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </StackItem>

        {/* ---------------- Right: documents in the selected folder ---------------- */}
        <StackItem className="col-span-12 lg:col-span-9">
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-5 py-2.5">
              <div className="relative min-w-[240px] flex-1">
                <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" strokeWidth={2} aria-hidden="true" />
                <input
                  type="search"
                  className="input input-sm pl-8"
                  value={query}
                  placeholder="Search documents by name or description"
                  aria-label="Search documents"
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              {hits !== null ? (
                <Label>
                  {searching ? "Searching…" : searchErr ? "- matches" : `${hits.length} ${hits.length === 1 ? "match" : "matches"}`}
                </Label>
              ) : null}
              {query ? (
                <Button size="sm" variant="ghost" onClick={() => setQuery("")}>Clear</Button>
              ) : null}
            </div>
            {hits !== null ? (
              <section aria-label="Search results">
                {searching && hits.length === 0 ? (
                  <Loading>Searching…</Loading>
                ) : searchErr ? (
                  <LoadError what="The search results" reason={searchErr.reason} onRetry={() => setSearchTry((n) => n + 1)} />
                ) : hits.length === 0 ? (
                  <Empty title="No documents match">Try a shorter word: the search matches names and descriptions.</Empty>
                ) : (
                  <div className="overflow-x-auto">
                    <div style={{ minWidth: SEARCH_COLS.minWidth }}>
                      <div className="grid gap-3 border-b border-line bg-surface-2 px-5 py-2" style={{ gridTemplateColumns: SEARCH_COLS.template }}>
                        <Label>Document</Label>
                        <Label>Folder</Label>
                        <Label>Status</Label>
                        <Label>Review due</Label>
                        <Label>Owner</Label>
                      </div>
                      <ul className="divide-y divide-line">
                        {hits.map((d) => {
                          const status = DOC_STATUS[d.status] || { label: d.status, tone: "muted" };
                          const days = d.days_until_review;
                          return (
                            <li key={d.id} className="grid items-center gap-3 px-5 py-3 transition-colors duration-150 ease-out hover:bg-surface-2" style={{ gridTemplateColumns: SEARCH_COLS.template }}>
                              <span className="flex min-w-0 items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => setViewing(documentViewerProps(d))}
                                  title="Open in browser"
                                  className="block min-w-0 max-w-full truncate text-left text-[13px] font-medium text-ink transition-colors duration-150 ease-out hover:text-accent"
                                >
                                  {d.name}
                                </button>
                                <IconButton label={`Download ${d.name}`} className="shrink-0" onClick={() => downloadFile(`/documents/${d.id}/download/`, d.name)}>
                                  <DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                                </IconButton>
                              </span>
                              <button
                                type="button"
                                onClick={() => jumpTo(d)}
                                title="Open this folder"
                                className="truncate text-left font-mono text-2xs uppercase tracking-label text-faint transition-colors duration-150 ease-out hover:text-accent"
                              >
                                {d.folder_path}
                              </button>
                              <span><Badge tone={status.tone} dot>{status.label}</Badge></span>
                              <span className="flex flex-col items-start gap-1">
                                <span className="tabular font-mono text-xs" style={{ color: toneVar(dueTone(days)) }}>{fmtDate(d.next_review_date)}</span>
                                <Badge tone={dueTone(days)} mono>{dueLabel(days)}</Badge>
                              </span>
                              <span className={cn("truncate text-xs", d.owner_name ? "text-muted" : "text-faint")}>{d.owner_name || "-"}</span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  </div>
                )}
              </section>
            ) : !folder ? (
              <Empty title="Select a folder" className="py-20">
                {treeErr
                  ? "The folder list did not load, so there is nothing to pick yet. Search above still looks across every document you can see."
                  : "Pick a folder on the left to see its documents, or search across all of them above."}
              </Empty>
            ) : (
              <>
                <PanelHeader title={folder.name}>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {canEdit ? (
                      <Button
                        size="sm"
                        variant="primary"
                        icon={<UploadIcon className="h-3.5 w-3.5" strokeWidth={2} />}
                        aria-expanded={showUpload}
                        aria-controls={showUpload ? "doc-upload-form" : undefined}
                        onClick={toggleUpload}
                        disabled={busy}
                      >
                        Upload document
                      </Button>
                    ) : null}
                    <Label>{countsKnown ? `${docs.length} ${docs.length === 1 ? "document" : "documents"}` : "- documents"}</Label>
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
                  {showUpload && canEdit ? (
                    <Collapse key="upload" open>
                      <form id="doc-upload-form" onSubmit={submitUpload} className="space-y-3 border-b border-line bg-surface-2 px-5 py-4">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div className="sm:col-span-2">
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
                            className="w-full max-w-md justify-start"
                            icon={<FileUpIcon className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />}
                            onClick={() => fileRef.current?.click()}
                            disabled={busy}
                          >
                            <span className={cn("truncate", !upload.file && "text-muted")}>{upload.file ? upload.file.name : "Choose file…"}</span>
                          </Button>
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" variant="primary" type="submit" disabled={busy || !upload.name.trim() || !upload.file}>
                            {busy ? "Uploading…" : "Upload"}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setShowUpload(false)} disabled={busy}>Cancel</Button>
                        </div>
                      </form>
                    </Collapse>
                  ) : null}
                </AnimatePresence>

                <AnimatePresence initial={false}>
                  {showPerms && canManage ? (
                    <Collapse key="perms" open>
                      <AccessEditor
                        perms={perms}
                        permsErr={permsErr}
                        onRetry={() => loadPerms(folder.id)}
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
                  <div style={{ minWidth: cols.minWidth }}>
                    <div className="grid gap-3 border-b border-line bg-surface-2 px-5 py-2" style={{ gridTemplateColumns: cols.template }}>
                      <Label>Document</Label>
                      <Label>Status</Label>
                      <Label>Review due</Label>
                      <Label>Owner</Label>
                      <Label>Version</Label>
                      <Label>Controls</Label>
                      {/* Named for screen readers only: the column is one
                          button wide, narrower than the word. */}
                      {canEdit ? <span className="sr-only">Actions</span> : null}
                    </div>
                    {docsLoading ? (
                      <Loading />
                    ) : docsErr ? (
                      <LoadError what="This folder's documents" reason={docsErr.reason} onRetry={() => loadDocs(folderId)} />
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
                                  className="grid items-center gap-3 px-5 py-3 transition-colors duration-150 ease-out hover:bg-surface-2"
                                  style={{ gridTemplateColumns: cols.template }}
                                >
                                  <span className="min-w-0">
                                    <span className="flex min-w-0 items-center gap-1">
                                      <button
                                        type="button"
                                        onClick={() => setViewing(documentViewerProps(d))}
                                        title="Open in browser"
                                        className="block min-w-0 max-w-full truncate text-left text-[13px] font-medium text-ink transition-colors duration-150 ease-out hover:text-accent"
                                      >
                                        {d.name}
                                      </button>
                                      <IconButton label={`Download ${d.name}`} className="shrink-0" onClick={() => downloadFile(`/documents/${d.id}/download/`, d.name)}>
                                        <DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                                      </IconButton>
                                    </span>
                                    <span className="block truncate font-mono text-2xs uppercase tracking-label text-faint">
                                      {d.folder_path}{d.control_id ? ` · ${d.control_id}` : ""}
                                    </span>
                                  </span>
                                  <span className="flex flex-col items-start gap-1">
                                    <Badge tone={status.tone} dot>{status.label}</Badge>
                                    {d.quarantined ? <Badge tone="danger" mono title={d.scan_signature}>quarantined</Badge> : null}
                                  </span>
                                  <span className="flex flex-col items-start gap-1">
                                    <span className="tabular font-mono text-xs" style={{ color: toneVar(dueTone(days)) }}>
                                      {fmtDate(d.next_review_date)}
                                    </span>
                                    <Badge tone={dueTone(days)} mono>{dueLabel(days)}</Badge>
                                  </span>
                                  <span className={cn("truncate text-xs", d.owner_name ? "text-muted" : "text-faint")}>{d.owner_name || "-"}</span>
                                  <span className="tabular font-mono text-xs text-muted">v{d.version}</span>
                                  <span className="flex flex-wrap gap-1" title={chips.length ? "Controls this document is linked to as evidence" : undefined}>
                                    {chips.length === 0 ? <span className="text-2xs text-faint">-</span> : null}
                                    {chips.slice(0, MAX_CHIPS).map((s) => (
                                      <Badge key={s.link_id} tone="accent" mono title={s.title}>{s.label}</Badge>
                                    ))}
                                    {chips.length > MAX_CHIPS ? <Badge tone="muted" mono>+{chips.length - MAX_CHIPS}</Badge> : null}
                                  </span>
                                  {canEdit ? (
                                    <span className="flex items-center justify-end">
                                      <RowActionsTrigger
                                        doc={d}
                                        busy={busy}
                                        open={actionsFor?.doc.id === d.id}
                                        onToggle={toggleActions}
                                      />
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

      <DocumentViewer open={!!viewing} {...(viewing || {})} onClose={() => setViewing(null)} />

      <AnimatePresence>
        {actionsFor ? (
          <DocActionsMenu
            key={actionsFor.doc.id}
            doc={actionsFor.doc}
            trigger={actionsFor.trigger}
            focusAt={actionsFor.focusAt}
            openRequest={actionsFor.openRequest}
            mapOpen={editor?.id === actionsFor.doc.id && editor.mode === "map"}
            renameOpen={editor?.id === actionsFor.doc.id && editor.mode === "rename"}
            onMap={() => toggleMap(actionsFor.doc)}
            onRename={() => toggleRename(actionsFor.doc)}
            onMarkReviewed={() => confirmMarkReviewed(actionsFor.doc)}
            onNewVersion={() => pickVersion(actionsFor.doc)}
            onClose={closeActions}
          />
        ) : null}
      </AnimatePresence>

      {/* Single hidden picker for "Upload new version": the row's menu records which document, then opens it. */}
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
