import { useEffect, useId, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CornerDownLeftIcon, FileTextIcon, SearchIcon, ShieldCheckIcon, UserIcon } from "lucide-react";
import api from "../../api/client.js";
import { useShell } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { CONTROL_STATUS } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { Dialog } from "../ui/Dialog.jsx";
import { Label } from "../ui/Panel.jsx";

const MIN_CHARS = 2;
const DEBOUNCE_MS = 220;
const PER_GROUP = 6;

// Each result links to its page with `?search=` set to the record's own
// reference or name (and `?framework=` for a control, whose reference is not
// unique across frameworks): the pages read those, filter to the record and,
// for a control that matches exactly, open it. Each section asks the endpoint
// the page itself lists from, so the palette can never show what that page
// refuses, and People is offered only to someone who can open the Users page.
const SECTIONS = [
  {
    key: "controls",
    label: "Controls",
    Icon: ShieldCheckIcon,
    url: "/controls/",
    // An auditor is refused the control library, so they are never asked.
    allowed: (me) => !me?.capabilities?.auditor,
    row: (c) => ({
      id: c.id,
      primary: c.control_id,
      title: c.title,
      secondary: c.framework,
      status: c.status,
      to: `/controls?${c.framework_key ? `framework=${encodeURIComponent(c.framework_key)}&` : ""}search=${encodeURIComponent(c.control_id)}`,
      rank: [c.control_id, c.title],
    }),
  },
  {
    key: "documents",
    label: "Documents",
    Icon: FileTextIcon,
    url: "/documents/",
    allowed: () => true,
    row: (d) => ({
      id: d.id,
      primary: d.name,
      secondary: d.folder_path,
      to: `/documents?search=${encodeURIComponent(d.name)}`,
      rank: [d.name],
    }),
  },
  {
    key: "people",
    label: "People",
    Icon: UserIcon,
    url: "/users/",
    // The directory answers any member, but the Users page it links to is for
    // whoever manages users; anyone else would be sent to a refusal. A 403 is
    // still handled below, and simply leaves People out.
    allowed: (me) => !me?.capabilities?.auditor && !!me?.capabilities?.manage_users,
    row: (u) => ({
      id: u.id,
      primary: u.full_name || u.username,
      secondary: [...new Set([u.job_title, u.role_detail?.name].filter(Boolean))].join(" · ") || u.email,
      to: `/users?search=${encodeURIComponent(u.username)}`,
      rank: [u.full_name || u.username, u.username],
    }),
  },
];

// The reference or name that equals the query ranks first, then the one it
// starts, then a title it starts, then anything that contains it, and the
// rest keep the order the API gave them.
function rankOf([key, text], q) {
  const k = String(key || "").toLowerCase();
  const t = String(text || "").toLowerCase();
  if (k === q) return 0;
  if (k.startsWith(q)) return 1;
  if (t.startsWith(q)) return 2;
  return k.includes(q) || t.includes(q) ? 3 : 4;
}

function PaletteBody({ onClose }) {
  const { me } = useShell();
  const navigate = useNavigate();
  const listId = useId();
  const [query, setQuery] = useState("");
  const [state, setState] = useState({ status: "idle", groups: [] });
  const [active, setActive] = useState(0);
  const sections = useMemo(() => SECTIONS.filter((s) => s.allowed(me)), [me]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < MIN_CHARS) {
      setState({ status: "idle", groups: [] });
      return undefined;
    }
    setState((was) => ({ ...was, status: "loading" }));
    // A stale answer is dropped, not cancelled: an aborted request is a
    // failed request to anything watching the network.
    let live = true;
    const timer = setTimeout(async () => {
      const lower = q.toLowerCase();
      const settled = await Promise.allSettled(sections.map((s) => api.get(s.url, { params: { search: q } })));
      if (!live) return;
      const groups = [];
      let failed = 0;
      settled.forEach((res, i) => {
        const section = sections[i];
        if (res.status === "rejected") {
          if (res.reason?.response?.status !== 403) failed += 1;
          return;
        }
        const list = res.value.data?.results || res.value.data || [];
        const rows = list
          .map((r, at) => ({ ...section.row(r), at }))
          .sort((a, b) => rankOf(a.rank, lower) - rankOf(b.rank, lower) || a.at - b.at)
          .slice(0, PER_GROUP);
        if (rows.length) groups.push({ ...section, rows });
      });
      setActive(0);
      setState({ status: failed === sections.length ? "error" : "done", groups });
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query, sections]);

  // One flat list for the arrow keys; each row knows its place in it.
  const options = useMemo(
    () => state.groups.flatMap((g) => g.rows.map((r) => ({ ...r, group: g.key, optionId: `${listId}-${g.key}-${r.id}` }))),
    [state.groups, listId]
  );
  const indexOf = useMemo(() => new Map(options.map((o, i) => [o.optionId, i])), [options]);
  const current = options[active];

  useEffect(() => {
    if (current) document.getElementById(current.optionId)?.scrollIntoView({ block: "nearest" });
  }, [current]);

  function go(option) {
    if (!option) return;
    onClose();
    navigate(option.to);
  }

  function onKeyDown(e) {
    if (!options.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(current);
    }
  }

  const q = query.trim();
  let message = null;
  if (q.length < MIN_CHARS) message = `Type ${MIN_CHARS} or more characters.`;
  else if (state.status === "loading" && !options.length) message = "Searching…";
  else if (state.status === "error") message = "Search is unavailable right now. Nothing has changed, so trying again is safe.";
  else if (state.status === "done" && !options.length) message = `Nothing matches "${q}".`;

  return (
    <div>
      <label htmlFor={`${listId}-q`} className="sr-only">Jump to a control, document or person</label>
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" strokeWidth={1.75} aria-hidden="true" />
        <input
          id={`${listId}-q`}
          type="text"
          role="combobox"
          aria-expanded={options.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={current?.optionId}
          autoComplete="off"
          spellCheck={false}
          placeholder="Jump to a control, document or person"
          className="input pl-9"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          onKeyDown={onKeyDown}
        />
      </div>

      <div className="sr-only" role="status" aria-live="polite">
        {message || (options.length ? `${options.length} ${options.length === 1 ? "result" : "results"}` : "")}
      </div>

      <div id={listId} role="listbox" aria-label="Results" className="mt-2 max-h-[min(52vh,420px)] overflow-y-auto">
        {message ? <p className="px-2 py-6 text-center text-[13px] text-muted" aria-hidden="true">{message}</p> : null}
        {state.groups.map((g) => (
          <div key={g.key} role="group" aria-labelledby={`${listId}-${g.key}-h`} className="mt-1 first:mt-0">
            <Label id={`${listId}-${g.key}-h`} className="block px-2 pb-1 pt-2">{g.label}</Label>
            {g.rows.map((r) => {
              const optionId = `${listId}-${g.key}-${r.id}`;
              const at = indexOf.get(optionId);
              const option = options[at];
              const on = at === active;
              const status = r.status ? CONTROL_STATUS[r.status] : null;
              return (
                <div
                  key={r.id}
                  id={optionId}
                  role="option"
                  aria-selected={on}
                  onMouseMove={() => { if (!on) setActive(at); }}
                  onClick={() => go(option)}
                  className={cn("flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2", on ? "bg-accent/10" : "hover:bg-ink/[0.04]")}
                >
                  <g.Icon className="h-4 w-4 shrink-0 text-muted" strokeWidth={1.75} aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-2">
                      <span className={cn("truncate text-[13px] font-medium text-ink", g.key === "controls" && "shrink-0 font-mono")}>{r.primary}</span>
                      {r.title ? <span className="truncate text-[13px] text-ink">{r.title}</span> : null}
                    </span>
                    {r.secondary ? <span className="block truncate text-xs text-muted">{r.secondary}</span> : null}
                  </span>
                  {status ? <Badge tone={status.tone}>{status.label}</Badge> : null}
                  {on ? <CornerDownLeftIcon className="h-3.5 w-3.5 shrink-0 text-muted" strokeWidth={1.75} aria-hidden="true" /> : null}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <p className="mt-3 border-t border-line pt-2.5 text-2xs text-muted">
        Up and Down to move, Enter to open, Esc to close.
      </p>
    </div>
  );
}

/** Ctrl K or Cmd K, or the search button in the top bar. One input, three
 * existing list endpoints, grouped results. */
export function SearchPalette({ open, onClose }) {
  return (
    <Dialog open={open} onClose={onClose} title="Jump to" description="Controls, documents and people in this workspace." placement="top">
      <PaletteBody onClose={onClose} />
    </Dialog>
  );
}
