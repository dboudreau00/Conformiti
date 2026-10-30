import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Search, X } from "lucide-react";
import api from "../api/client.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { errorText, loadFailReason } from "../utils/a11y.js";

const ACTION_TONE = {
  create: "success",
  update: "info",
  delete: "danger",
  login: "success",
  login_failed: "danger",
  logout: "muted",
};

const DAY_RANGES = [
  { id: "7", label: "Last 7 days" },
  { id: "30", label: "Last 30 days" },
  { id: "90", label: "Last 90 days" },
  { id: "", label: "All time" },
];

const EMPTY_FILTERS = { action: "", type: "", user: "", days: "30", q: "" };
const EMPTY_FACETS = { actions: [], object_types: [], users: [] };

function fmtWhen(ts) {
  return ts ? ts.slice(0, 16).replace("T", " ") : "";
}

export default function AuditLog({ me }) {
  const caps = me?.capabilities || {};
  const canSee = !!(caps.manage_users || caps.auditor || caps.view_all);

  // `from` is where the latest page starts, so only fresh rows animate in on "Load more".
  const [list, setList] = useState({ rows: [], from: 0 });
  const [next, setNext] = useState(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState(EMPTY_FACETS);
  const [f, setF] = useState(EMPTY_FILTERS);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [err, setErr] = useState(null);
  // First page failed: that is not an empty trail, so the empty states must not stand in for it. Separate from `err`,
  // which the facets request also sets.
  const [loadFailed, setLoadFailed] = useState(false);
  const loadSeq = useRef(0);

  function query(p) {
    const parts = [`page=${p}`];
    if (f.action) parts.push(`action=${encodeURIComponent(f.action)}`);
    if (f.type) parts.push(`object_type=${encodeURIComponent(f.type)}`);
    if (f.user) parts.push(`user=${encodeURIComponent(f.user)}`);
    if (f.days) parts.push(`days=${encodeURIComponent(f.days)}`);
    if (f.q) parts.push(`search=${encodeURIComponent(f.q)}`);
    return `/audit-log/?${parts.join("&")}`;
  }

  async function load(p) {
    const seq = ++loadSeq.current;
    setLoading(true);
    setErr(null);
    setLoadFailed(false);
    try {
      const { data } = await api.get(query(p));
      if (seq !== loadSeq.current) return;
      const results = data.results || data;
      setList((prev) => {
        const base = p === 1 ? [] : prev.rows;
        return { rows: base.concat(results), from: base.length };
      });
      setNext(data.next || null);
      setTotal(data.count ?? results.length);
      setPage(p);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      if (e?.response?.status === 403) {
        setDenied(true);
        return;
      }
      setErr(errorText(e, "Couldn't load the audit trail."));
      // A failed "Load more" keeps the rows; a failed first page must drop them, or they describe a query that did not run.
      if (p === 1) {
        setList({ rows: [], from: 0 });
        setNext(null);
        setLoadFailed({ reason: loadFailReason(e) });
      }
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (!canSee) return;
    load(1);
  }, [f, canSee]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!canSee) return;
    api
      .get("/audit-log/facets/")
      .then((r) =>
        setFacets({
          actions: r.data?.actions || [],
          object_types: r.data?.object_types || [],
          users: r.data?.users || [],
        })
      )
      .catch((e) => {
        // A 403 is reported by the list request; anything else must surface, not leave the filters silently empty.
        if (e?.response?.status !== 403) setErr(errorText(e, "Couldn't load the filter options."));
      });
  }, [canSee]);

  function submitSearch(e) {
    e.preventDefault();
    setF({ ...f, q: q.trim() });
  }

  function clearFilters() {
    setQ("");
    setF({ ...EMPTY_FILTERS, days: f.days });
  }

  if (!canSee || denied) {
    return (
      <PanelTransition>
        <Panel>
          <Empty title="The audit trail is restricted" />
        </Panel>
      </PanelTransition>
    );
  }

  const { rows, from } = list;
  const filtered = !!(f.q || f.action || f.type || f.user);
  // The time range is not reset by Clear and starts at 30 days, so an empty page inside it is not an empty trail.
  const range = f.days ? DAY_RANGES.find((d) => d.id === f.days) : null;
  const initialLoading = loading && rows.length === 0;

  let emptyState;
  if (loadFailed) {
    emptyState = <LoadError what="The audit trail" reason={loadFailed.reason} onRetry={() => load(1)} />;
  } else if (filtered) {
    emptyState = <Empty title="No entries match these filters" />;
  } else if (f.days) {
    emptyState = (
      <Empty
        title={`No entries in the ${range ? range.label.toLowerCase() : "selected time range"}`}
        action={<Button size="sm" variant="secondary" onClick={() => setF({ ...f, days: "" })}>Show all time</Button>}
      />
    );
  } else {
    emptyState = <Empty title="No entries yet" />;
  }

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        <StackItem className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Action"
              className="input input-sm w-auto min-w-[130px]"
              value={f.action}
              onChange={(e) => setF({ ...f, action: e.target.value })}
            >
              <option value="">All actions</option>
              {facets.actions.map((a) => (
                <option key={a} value={a}>{a.replace(/_/g, " ")}</option>
              ))}
            </select>
            <select
              aria-label="Record type"
              className="input input-sm w-auto min-w-[150px]"
              value={f.type}
              onChange={(e) => setF({ ...f, type: e.target.value })}
            >
              <option value="">All record types</option>
              {facets.object_types.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select
              aria-label="Actor"
              className="input input-sm w-auto min-w-[130px]"
              value={f.user}
              onChange={(e) => setF({ ...f, user: e.target.value })}
            >
              <option value="">All users</option>
              {facets.users.map((u) => (
                <option key={u.id} value={u.id}>{u.username}</option>
              ))}
            </select>
            <select
              aria-label="Time range"
              className="input input-sm w-auto min-w-[130px]"
              value={f.days}
              onChange={(e) => setF({ ...f, days: e.target.value })}
            >
              {DAY_RANGES.map((d) => (
                <option key={d.id} value={d.id}>{d.label}</option>
              ))}
            </select>
          </div>

          <form className="flex flex-wrap items-center gap-2" onSubmit={submitSearch} role="search">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
                strokeWidth={2}
                aria-hidden="true"
              />
              <input
                type="text"
                aria-label="Search audit log"
                placeholder="Search detail, record, user, IP…"
                className="input input-sm w-[280px] pl-8"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <Button type="submit" size="sm" variant="primary" disabled={loading}>
              Search
            </Button>
            {filtered ? (
              <Button
                size="sm"
                variant="ghost"
                icon={<X className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                onClick={clearFilters}
                disabled={loading}
              >
                Clear
              </Button>
            ) : null}
          </form>
        </StackItem>

        {err ? (
          <StackItem>
            <div className="notice notice-err" role="alert">{err}</div>
          </StackItem>
        ) : null}

        <StackItem>
          <Panel className="overflow-hidden">
            <PanelHeader
              title="Audit trail"
              meta={
                initialLoading || loadFailed ? null : (
                  <span className="tabular">
                    {total.toLocaleString()} {total === 1 ? "entry" : "entries"}
                  </span>
                )
              }
            />
            {initialLoading ? (
              <Loading>Loading audit trail…</Loading>
            ) : rows.length === 0 ? (
              emptyState
            ) : (
              <div className="overflow-x-auto" role="region" aria-label="Audit log entries" tabIndex={0}>
                <table className="w-full min-w-[1040px] border-collapse text-left">
                  <thead className="border-b border-line bg-surface-2">
                    <tr>
                      <th scope="col" className="table-head w-[150px] px-5 py-2 font-normal">When</th>
                      <th scope="col" className="table-head w-[190px] px-5 py-2 font-normal">Actor</th>
                      <th scope="col" className="table-head w-[120px] px-5 py-2 font-normal">Action</th>
                      <th scope="col" className="table-head w-[210px] px-5 py-2 font-normal">Record</th>
                      <th scope="col" className="table-head px-5 py-2 font-normal">Detail</th>
                      <th scope="col" className="table-head w-[140px] px-5 py-2 font-normal">IP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {rows.map((r, i) => {
                      const tone = ACTION_TONE[r.action] || "muted";
                      const actor = r.user_name || r.username || "system";
                      return (
                        <motion.tr
                          key={r.id}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          transition={{ duration: 0.2, ease: EASE, delay: Math.min(Math.max(i - from, 0), 20) * 0.02 }}
                          className="align-middle transition-colors duration-150 ease-out hover:bg-surface-2/60"
                        >
                          <td className="tabular whitespace-nowrap px-5 py-2.5 font-mono text-xs text-muted">
                            {fmtWhen(r.timestamp)}
                          </td>
                          <td className="max-w-0 px-5 py-2.5">
                            <span className="block truncate text-[13px] font-medium text-ink">{actor}</span>
                            {r.username ? (
                              <span className="block truncate font-mono text-2xs text-accent">{r.username}</span>
                            ) : null}
                          </td>
                          <td className="whitespace-nowrap px-5 py-2.5">
                            <Badge tone={tone} mono dot>{String(r.action || "").replace(/_/g, " ") || "-"}</Badge>
                          </td>
                          <td className="max-w-0 truncate px-5 py-2.5 font-mono text-xs text-ink">
                            {r.object_type ? (
                              <>
                                {r.object_type}
                                {r.object_id ? <span className="text-muted"> #{r.object_id}</span> : null}
                              </>
                            ) : (
                              <span className="text-faint">-</span>
                            )}
                          </td>
                          <td className="max-w-0 px-5 py-2.5">
                            {r.detail ? (
                              <span className="line-clamp-2 text-[13px] leading-snug text-ink" title={r.detail}>
                                {r.detail}
                              </span>
                            ) : (
                              <span className="text-[13px] text-faint">-</span>
                            )}
                          </td>
                          <td className="tabular whitespace-nowrap px-5 py-2.5 font-mono text-xs text-muted">
                            {r.ip_address || <span className="text-faint">-</span>}
                          </td>
                        </motion.tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {!initialLoading && rows.length > 0 ? (
              <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
                <Label className="tabular">
                  Showing {rows.length.toLocaleString()} of {total.toLocaleString()}
                </Label>
                {next ? (
                  <Button size="sm" onClick={() => load(page + 1)} disabled={loading}>
                    {loading ? "Loading…" : "Load more"}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </Panel>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
