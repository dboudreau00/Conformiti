import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRightIcon, DownloadIcon, PaperclipIcon, SearchIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { ControlDetail } from "../components/controls/ControlDetail.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Chip, SegmentedControl } from "../components/ui/SegmentedControl.jsx";
import { usePage } from "../components/ui/ShowMore.jsx";
import { useShell } from "../shell.js";
import { errorText, loadFailReason } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";
import { useDeepLink } from "../utils/deepLink.js";
import { CONTROL_STATUS, READINESS_BAND } from "../utils/tone.js";

const STATUS_KEYS = Object.keys(CONTROL_STATUS);
// From lg up a row is a seven-column grid; below it the cells wrap, so a phone never scrolls the register sideways.
const GRID = "lg:grid lg:min-w-[960px] lg:grid-cols-[110px_minmax(0,1fr)_120px_130px_130px_120px_80px] lg:items-center lg:gap-4";
const HEADINGS = ["Ref", "Control", "Framework", "Status", "Owner", "Readiness", "Evidence"];

export default function Controls({ me }) {
  const { refreshCounts } = useShell();

  const [frameworks, setFrameworks] = useState(null);
  const [wantedFramework, setFramework] = useState("all");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [controls, setControls] = useState([]);
  const [loadedFor, setLoadedFor] = useState(null);
  const [openRef, setOpenRef] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [exporting, setExporting] = useState(false);
  // A failed load is not an empty catalogue: showing it as one would tell the reader to seed a framework they have.
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const [users, setUsers] = useState(null);
  const [docChoices, setDocChoices] = useState(null);
  const [docsTruncated, setDocsTruncated] = useState(undefined);
  const [choicesError, setChoicesError] = useState("");
  const choicesRequested = useRef(false);

  const canManage = !!me?.capabilities?.manage_frameworks;
  const canLink = canManage || !!me?.capabilities?.manage_documents;

  // A link naming a framework this workspace lacks shows every framework instead of asking for a missing register.
  const framework =
    frameworks && wantedFramework !== "all" && !frameworks.some((f) => f.key === wantedFramework) ? "all" : wantedFramework;

  // A link replaces the view: ?framework= picks the tab, ?search= fills the box, and the status filter resets so an
  // earlier choice cannot hide the control it names.
  useDeepLink((params) => {
    const key = params.get("framework");
    const text = params.get("search");
    if (key === null && text === null) return;
    setFramework(key || "all");
    setQuery(text ?? "");
    setStatus("all");
    setOpenRef(text && text.trim() ? text.trim().toLowerCase() : null);
  });

  useEffect(() => {
    let alive = true;
    fetchAll("/frameworks/")
      .then((list) => {
        if (alive) setFrameworks(list);
      })
      .catch((e) => {
        if (!alive) return;
        setFrameworks([]);
        setLoading(false);
        setLoadFailed({ reason: loadFailReason(e) });
      });
    return () => {
      alive = false;
    };
  }, [attempt]);

  useEffect(() => {
    if (!frameworks) return;
    const keys = framework === "all" ? frameworks.map((f) => f.key) : [framework];
    let alive = true;
    setLoading(true);
    setExpanded(null);
    Promise.all(keys.map((k) => api.get(`/frameworks/${encodeURIComponent(k)}/controls/`)))
      .then((rs) => {
        if (!alive) return;
        setControls(rs.flatMap((r) => r.data.results || r.data));
        setLoadedFor(framework);
        // A failure on another tab is over once this one has loaded.
        if (keys.length) setLoadFailed(false);
      })
      .catch((e) => {
        if (!alive) return;
        setControls([]);
        setLoadFailed({ reason: loadFailReason(e) });
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [framework, frameworks, attempt]);

  // Opens the control a link named once its register is here; a reference in several frameworks, or none, opens nothing.
  useEffect(() => {
    if (openRef === null || loading || loadedFor !== framework) return;
    const hits = controls.filter((c) => String(c.control_id).toLowerCase() === openRef);
    if (hits.length === 1) setExpanded(hits[0].id);
    setOpenRef(null);
  }, [openRef, loading, loadedFor, framework, controls]);

  useEffect(() => {
    if (!canManage) return;
    let alive = true;
    fetchAll("/users/")
      .then((rows) => {
        // A deactivated person cannot be picked; the open control's current owner is added back by its own select.
        if (alive) setUsers(rows.filter((u) => u.is_active));
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
      .then((r) => {
        setChoicesError("");
        setDocChoices(r.data.documents || []);
        setDocsTruncated(r.data.documents_truncated);
      })
      .catch((e) => {
        choicesRequested.current = false;
        setChoicesError(errorText(e, "Couldn't load the document list."));
      });
  }, []);

  useEffect(() => {
    if (expanded !== null && canLink) ensureChoices();
  }, [expanded, canLink, ensureChoices]);

  const patchControl = useCallback(
    async (id, patch) => {
      const { data } = await api.patch(`/controls/${id}/`, patch);
      setControls((cs) => cs.map((c) => (c.id === id ? { ...c, ...data } : c)));
      refreshCounts();
    },
    [refreshCounts]
  );

  const applyScore = useCallback((id, score) => {
    setControls((cs) => cs.map((c) => (c.id === id ? { ...c, ...score } : c)));
  }, []);

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
      // The search box filters the rows on screen; the file holds the same rows.
      if (query.trim()) params.set("q", query.trim());
      const qs = params.toString();
      await downloadFile(`/controls/export/${qs ? `?${qs}` : ""}`, "controls.csv");
    } catch (e) {
      setPageError(errorText(e, "Couldn't export the control register."));
    } finally {
      setExporting(false);
    }
  }

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
  // Rows, the empty note and "Show more" belong to a register that loaded and has frameworks.
  const listed = ready && !loadFailed && frameworks.length > 0;
  const page = usePage(rows, 100, [framework, status, query]);

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
            collapseAfter={5}
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
              {key === "all" ? "All statuses" : CONTROL_STATUS[key].label}
            </Chip>
          ))}
        </StackItem>

        <StackItem>
          {pageError ? (
            <div className="notice notice-err mb-4" role="alert">{pageError}</div>
          ) : null}

          <Panel className="overflow-hidden">
            <PanelHeader title="Control register">
              {/* The second number is the whole register, filter or not: it shows every page of results arrived. */}
              <Label className="tabular">
                {ready ? `Showing ${page.shown.toLocaleString()} of ${controls.length.toLocaleString()}` : "Loading"}
              </Label>
            </PanelHeader>

            <div className="overflow-x-auto">
              {/* A table to a screen reader: the headings are columnheaders, and below lg they are hidden from sight only. */}
              <div role="table" aria-label="Control register">
                <div role="rowgroup" className="max-lg:sr-only">
                  <div role="row" className={cn("border-b border-line bg-surface-2 px-5 py-2", GRID)}>
                    {HEADINGS.map((h) => (
                      <Label key={h} role="columnheader" className={h === "Evidence" ? "text-right" : undefined}>
                        {h}
                      </Label>
                    ))}
                  </div>
                </div>

                {listed ? (
                  <ul role="rowgroup" className="[&>li:first-child>[role=row]]:border-t-0">
                    <AnimatePresence initial={false}>
                      {page.visible.map((control) => (
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
                            docsTruncated={docsTruncated}
                            choicesError={choicesError}
                            onPatch={patchControl}
                            onEvidenceDelta={bumpEvidence}
                            onScore={applyScore}
                          />
                        </ControlRow>
                      ))}
                    </AnimatePresence>
                  </ul>
                ) : null}
              </div>

              {!ready ? (
                <Loading>Loading controls…</Loading>
              ) : loadFailed ? (
                <LoadError
                  what="The control register"
                  reason={loadFailed.reason}
                  onRetry={() => {
                    setLoadFailed(false);
                    setPageError("");
                    setLoading(true);
                    setAttempt((a) => a + 1);
                  }}
                />
              ) : frameworks.length === 0 ? (
                <Empty title="No frameworks yet" />
              ) : null}
              {listed && rows.length === 0 ? (
                <div className="border-t border-line">
                  {controls.length === 0 ? (
                    <Empty title={framework === "all" ? "No controls yet" : "No controls in this framework"} />
                  ) : (
                    <Empty
                      title="No controls match these filters"
                      action={
                        <Button
                          size="sm"
                          onClick={() => {
                            setQuery("");
                            setStatus("all");
                            setFramework("all");
                          }}
                        >
                          Clear filters
                        </Button>
                      }
                    />
                  )}
                </div>
              ) : null}
              {listed && page.remaining ? (
                <div className="border-t border-line px-5 py-3 text-center">
                  <Button size="sm" variant="secondary" onClick={page.more}>
                    Show {Math.min(page.size, page.remaining)} more of {page.remaining.toLocaleString()}
                  </Button>
                </div>
              ) : null}
            </div>
          </Panel>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}

function ControlRow({ control, expanded, onToggle, children }) {
  const meta = CONTROL_STATUS[control.status] || { label: control.status, tone: "muted" };
  const band = READINESS_BAND[control.readiness_band] || READINESS_BAND.not_started;
  const bodyId = `control-detail-${control.id}`;
  return (
    <motion.li
      role="none"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18, ease: EASE }}
    >
      {/* The button in the first cell is the control; the row's own click is the same toggle for a pointer. */}
      <div
        role="row"
        onClick={onToggle}
        className={cn(
          "flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line px-4 py-3 text-left lg:px-5",
          "transition-colors duration-150 ease-out hover:bg-surface-2 has-[:focus-visible]:bg-surface-2",
          expanded && "bg-surface-2",
          GRID
        )}
      >
        <div role="cell" className="min-w-0">
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={bodyId}
            aria-label={`${control.control_id}, ${control.title}`}
            className="flex max-w-full items-center gap-1.5 text-left"
          >
            <ChevronRightIcon
              className={cn("h-3.5 w-3.5 shrink-0 text-faint transition-transform duration-150 ease-out", expanded && "rotate-90")}
              strokeWidth={2}
              aria-hidden="true"
            />
            <span className="min-w-0 truncate font-mono text-xs text-accent">{control.control_id}</span>
          </button>
        </div>
        <div role="cell" className="min-w-0 flex-1 basis-[calc(100%-7rem)]">
          <span className="block truncate text-[13px] text-ink" title={control.title}>{control.title}</span>
        </div>
        <div role="cell" className="min-w-0 max-w-full truncate text-xs text-muted" title={control.framework}>{control.framework}</div>
        <div role="cell">
          <Badge tone={meta.tone} dot>{meta.label}</Badge>
        </div>
        <div role="cell" className={cn("min-w-0 max-w-full truncate text-xs", control.owner_name ? "text-muted" : "text-danger")}>
          {control.owner_name || "Unassigned"}
        </div>
        <div role="cell" className="flex items-center gap-1.5">
          {control.readiness_score === null ? (
            <Badge tone="muted">Excluded</Badge>
          ) : (
            <>
              <span className="tabular font-mono text-xs text-ink">{control.readiness_score}</span>
              <Badge tone={band.tone}>{band.label}</Badge>
            </>
          )}
        </div>
        <div role="cell" className="tabular flex items-center justify-end gap-1 font-mono text-xs text-muted">
          <PaperclipIcon className="h-3 w-3 text-faint" strokeWidth={2} aria-hidden="true" />
          {control.evidence_count || 0}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {expanded ? (
          <Collapse key="detail" open className="border-t border-line bg-surface-2">
            <div role="row">
              <div role="cell" aria-colspan={HEADINGS.length} id={bodyId}>{children}</div>
            </div>
          </Collapse>
        ) : null}
      </AnimatePresence>
    </motion.li>
  );
}
