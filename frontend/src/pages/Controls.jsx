import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRightIcon, DownloadIcon, PaperclipIcon, SearchIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { ControlDetail } from "../components/controls/ControlDetail.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Chip, SegmentedControl } from "../components/ui/SegmentedControl.jsx";
import { useShell } from "../shell.js";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";
import { CONTROL_STATUS } from "../utils/tone.js";

const STATUS_KEYS = Object.keys(CONTROL_STATUS);
const GRID = "grid-cols-[110px_minmax(0,1fr)_130px_140px_150px_90px]";

export default function Controls({ me }) {
  const { refreshCounts } = useShell();

  const [frameworks, setFrameworks] = useState(null); // null until loaded
  const [framework, setFramework] = useState("all");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [controls, setControls] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [exporting, setExporting] = useState(false);

  // Pick-lists shared by every expanded row.
  const [users, setUsers] = useState(null); // null = not loaded / unavailable
  const [docChoices, setDocChoices] = useState(null);
  const [choicesError, setChoicesError] = useState("");
  const choicesRequested = useRef(false);

  const canManage = !!me?.capabilities?.manage_frameworks;
  const canLink = canManage || !!me?.capabilities?.manage_documents;

  // ---- data ----------------------------------------------------------------
  useEffect(() => {
    let alive = true;
    // Paginated at 50 — follow `next` so every framework reaches the filter
    // (and the "all frameworks" fetch below covers the whole catalog).
    fetchAll("/frameworks/")
      .then((list) => {
        if (alive) setFrameworks(list);
      })
      .catch((e) => {
        if (!alive) return;
        setFrameworks([]);
        setLoading(false);
        setPageError(errorText(e, "Couldn't load frameworks."));
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!frameworks) return;
    const keys = framework === "all" ? frameworks.map((f) => f.key) : [framework];
    let alive = true;
    setLoading(true);
    setExpanded(null);
    Promise.all(keys.map((k) => api.get(`/frameworks/${k}/controls/`)))
      .then((rs) => {
        if (alive) setControls(rs.flatMap((r) => r.data.results || r.data));
      })
      .catch((e) => {
        if (!alive) return;
        setControls([]);
        setPageError(errorText(e, "Couldn't load controls."));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [framework, frameworks]);

  // Owner pick-list: only needed by users who can reassign controls.
  useEffect(() => {
    if (!canManage) return;
    let alive = true;
    fetchAll("/users/")
      .then((rows) => {
        if (alive) setUsers(rows);
      })
      .catch((e) => {
        if (alive) setPageError(errorText(e, "Couldn't load the user list; owners can't be reassigned right now."));
      });
    return () => {
      alive = false;
    };
  }, [canManage]);

  const ensureChoices = useCallback(() => {
    if (choicesRequested.current) return;
    choicesRequested.current = true;
    api
      .get("/control-evidence/choices/")
      .then((r) => setDocChoices(r.data.documents || []))
      .catch((e) => {
        choicesRequested.current = false;
        setChoicesError(errorText(e, "Couldn't load the document list."));
      });
  }, []);

  useEffect(() => {
    if (expanded !== null && canLink) ensureChoices();
  }, [expanded, canLink, ensureChoices]);

  // ---- writes --------------------------------------------------------------
  const patchControl = useCallback(
    async (id, patch) => {
      const { data } = await api.patch(`/controls/${id}/`, patch);
      setControls((cs) => cs.map((c) => (c.id === id ? { ...c, ...data } : c)));
      refreshCounts();
    },
    [refreshCounts]
  );

  const bumpEvidence = useCallback((id, delta) => {
    setControls((cs) =>
      cs.map((c) => (c.id === id ? { ...c, evidence_count: Math.max(0, (c.evidence_count || 0) + delta) } : c))
    );
  }, []);

  async function exportCsv() {
    setExporting(true);
    setPageError("");
    try {
      const params = new URLSearchParams();
      if (framework !== "all") params.set("category__framework__key", framework);
      if (status !== "all") params.set("status", status);
      const qs = params.toString();
      await downloadFile(`/controls/export/${qs ? `?${qs}` : ""}`, "controls.csv");
    } catch (e) {
      setPageError(errorText(e, "Couldn't export the control register."));
    } finally {
      setExporting(false);
    }
  }

  // ---- derived -------------------------------------------------------------
  const statusCounts = useMemo(() => {
    const counts = { all: controls.length };
    for (const k of STATUS_KEYS) counts[k] = 0;
    for (const c of controls) counts[c.status] = (counts[c.status] || 0) + 1;
    return counts;
  }, [controls]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return controls.filter(
      (c) =>
        (status === "all" || c.status === status) &&
        (q === "" || `${c.control_id} ${c.title}`.toLowerCase().includes(q))
    );
  }, [controls, status, query]);

  const frameworkOptions = useMemo(() => {
    const list = frameworks || [];
    return [
      { id: "all", label: "All frameworks", count: list.reduce((n, f) => n + (f.control_count || 0), 0) },
      ...list.map((f) => ({ id: f.key, label: f.name, count: f.control_count })),
    ];
  }, [frameworks]);

  const ready = frameworks !== null && !loading;

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        <StackItem className="flex flex-wrap items-center justify-between gap-3">
          <SegmentedControl
            layoutId="controls-framework"
            ariaLabel="Filter by framework"
            value={framework}
            onChange={setFramework}
            options={frameworkOptions}
          />

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <SearchIcon
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
                strokeWidth={2}
                aria-hidden="true"
              />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search reference or title"
                aria-label="Search controls"
                type="search"
                className="h-8 w-[260px] max-w-full rounded-lg border border-line bg-surface pl-8 pr-3 text-[13px] text-ink placeholder:text-faint transition-colors duration-150 ease-out focus:border-accent focus:outline-none"
              />
            </div>
            <Button
              size="sm"
              onClick={exportCsv}
              disabled={exporting || !ready}
              icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
            >
              {exporting ? "Exporting…" : "Export CSV"}
            </Button>
          </div>
        </StackItem>

        <StackItem className="flex flex-wrap gap-2">
          {["all", ...STATUS_KEYS].map((key) => (
            <Chip
              key={key}
              active={status === key}
              onClick={() => setStatus(key)}
              tone={key === "all" ? undefined : CONTROL_STATUS[key].tone}
              count={statusCounts[key] || 0}
            >
              {key === "all" ? "Every status" : CONTROL_STATUS[key].label}
            </Chip>
          ))}
        </StackItem>

        <StackItem>
          {pageError ? (
            <div className="notice notice-err mb-4" role="alert">{pageError}</div>
          ) : null}

          <Panel className="overflow-hidden">
            <PanelHeader title="Control register">
              <Label className="tabular">
                {ready ? `Showing ${rows.length} of ${controls.length}` : "Loading"}
              </Label>
            </PanelHeader>

            <div className="overflow-x-auto">
              <div className={cn("grid min-w-[860px] items-center gap-4 border-b border-line bg-surface-2 px-5 py-2", GRID)}>
                {["Ref", "Control", "Framework", "Status", "Owner", "Evidence"].map((h) => (
                  <Label key={h} className={h === "Evidence" ? "text-right" : undefined}>
                    {h}
                  </Label>
                ))}
              </div>

              {!ready ? (
                <Loading>Loading controls…</Loading>
              ) : frameworks.length === 0 ? (
                <Empty title="No frameworks available">Seed a framework to populate the control register.</Empty>
              ) : (
                <ul className="min-w-[860px] divide-y divide-line">
                  <AnimatePresence initial={false}>
                    {rows.map((control) => (
                      <ControlRow
                        key={control.id}
                        control={control}
                        expanded={expanded === control.id}
                        onToggle={() => setExpanded(expanded === control.id ? null : control.id)}
                      >
                        <ControlDetail
                          control={control}
                          canManage={canManage}
                          canLink={canLink}
                          users={users}
                          docChoices={docChoices}
                          choicesError={choicesError}
                          onPatch={patchControl}
                          onEvidenceDelta={bumpEvidence}
                        />
                      </ControlRow>
                    ))}
                  </AnimatePresence>
                  {rows.length === 0 ? (
                    <li>
                      <Empty title="No controls match these filters">
                        Clear the search or widen the status selection.
                      </Empty>
                    </li>
                  ) : null}
                </ul>
              )}
            </div>
          </Panel>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}

function ControlRow({ control, expanded, onToggle, children }) {
  const meta = CONTROL_STATUS[control.status] || { label: control.status, tone: "muted" };
  const bodyId = `control-detail-${control.id}`;
  return (
    <motion.li
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18, ease: EASE }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={bodyId}
        className={cn(
          "grid w-full items-center gap-4 px-5 py-3 text-left",
          "transition-colors duration-150 ease-out hover:bg-surface-2",
          expanded && "bg-surface-2",
          GRID
        )}
      >
        <span className="flex items-center gap-1.5">
          <ChevronRightIcon
            className={cn("h-3.5 w-3.5 shrink-0 text-faint transition-transform duration-150 ease-out", expanded && "rotate-90")}
            strokeWidth={2}
            aria-hidden="true"
          />
          <span className="truncate font-mono text-xs text-accent">{control.control_id}</span>
        </span>
        <span className="truncate text-[13px] text-ink" title={control.title}>{control.title}</span>
        <span className="truncate text-xs text-muted" title={control.framework}>{control.framework}</span>
        <span>
          <Badge tone={meta.tone} dot>{meta.label}</Badge>
        </span>
        <span className={cn("truncate text-xs", control.owner_name ? "text-muted" : "text-danger")}>
          {control.owner_name || "Unassigned"}
        </span>
        <span className="tabular flex items-center justify-end gap-1 font-mono text-xs text-muted">
          <PaperclipIcon className="h-3 w-3 text-faint" strokeWidth={2} aria-hidden="true" />
          {control.evidence_count || 0}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {expanded ? (
          <Collapse key="detail" open className="border-t border-line bg-surface-2">
            <div id={bodyId}>{children}</div>
          </Collapse>
        ) : null}
      </AnimatePresence>
    </motion.li>
  );
}
