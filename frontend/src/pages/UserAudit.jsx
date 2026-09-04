import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Download, Plus, X } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Meter } from "../components/ui/Meter.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";
import { toneVar } from "../utils/tone.js";

const DECISION_TONE = { keep: "success", modify: "warning", revoke: "danger", pending: "muted" };
const DECISIONS = [
  { id: "keep", label: "Keep" },
  { id: "modify", label: "Modify" },
  { id: "revoke", label: "Revoke" },
];
const REVIEW_STATUS = {
  open: { label: "Open", tone: "info" },
  completed: { label: "Completed", tone: "success" },
};
const COLUMNS = ["User", "Role", "Active", "Last login", "Grants", "Capabilities", "Decision", "Notes"];
// One template for the header row and every body row so the columns stay aligned.
const GRID =
  "grid-cols-[minmax(220px,1.4fr)_minmax(130px,0.9fr)_84px_104px_72px_minmax(170px,1fr)_240px_minmax(200px,1fr)]";

function fmtDate(s) {
  return s ? s.slice(0, 10) : "never";
}

/** Keep / Modify / Revoke radio group with a spring-animated tone wash, plus a
 * "pending" marker or a reset affordance so a decision can be cleared again. */
function DecisionControl({ item, disabled, onChange }) {
  const name = item.full_name || item.username;
  const decision = item.decision;
  return (
    <span className="flex items-center gap-2">
      <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5" role="radiogroup" aria-label={`Decision for ${name}`}>
        {DECISIONS.map((d) => {
          const on = decision === d.id;
          return (
            <button
              key={d.id}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={disabled}
              onClick={() => { if (!on) onChange(d.id); }}
              className={cn(
                "relative h-6 rounded-md px-2 text-2xs font-medium transition-colors duration-150 ease-out",
                "disabled:cursor-not-allowed disabled:opacity-60",
                on ? "text-ink" : "text-faint hover:text-muted"
              )}
            >
              {on ? (
                <motion.span
                  layoutId={`decision-${item.id}`}
                  className="absolute inset-0 rounded-md"
                  style={{ backgroundColor: toneVar(DECISION_TONE[d.id], 0.16) }}
                  transition={{ type: "spring", stiffness: 520, damping: 38 }}
                  aria-hidden="true"
                />
              ) : null}
              <span className="relative">{d.label}</span>
            </button>
          );
        })}
      </div>
      {decision === "pending" ? (
        <Badge tone="muted" mono>pending</Badge>
      ) : (
        <button
          type="button"
          aria-label={`Reset decision for ${name} to pending`}
          title="Reset to pending"
          disabled={disabled}
          onClick={() => onChange("pending")}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-faint transition-colors duration-150 ease-out hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
        >
          <X className="h-3.5 w-3.5" strokeWidth={2} />
        </button>
      )}
    </span>
  );
}

export default function UserAudit({ me }) {
  const canWrite = !!me?.capabilities?.manage_users;

  const [reviews, setReviews] = useState([]);
  const [review, setReview] = useState(null);
  const [items, setItems] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState(null);
  const [denied, setDenied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [busy, setBusy] = useState(null); // "start" | "complete" | "export"
  const [savingId, setSavingId] = useState(null);
  const loadSeq = useRef(0);

  async function selectReview(rev) {
    const seq = ++loadSeq.current;
    setReview(rev);
    setMsg(null);
    setDrafts({});
    setItemsLoading(true);
    try {
      const r = await api.get(`/access-review-items/?review=${rev.id}`);
      if (seq !== loadSeq.current) return;
      setItems(r.data.results || r.data);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setItems([]);
      setMsg({ ok: false, text: errorText(e, "Couldn't load the review rows.") });
    } finally {
      if (seq === loadSeq.current) setItemsLoading(false);
    }
  }

  async function loadReviews(selectId) {
    try {
      // Paginated at 50 — follow `next` so older reviews stay selectable.
      const list = await fetchAll("/access-reviews/");
      setReviews(list);
      const pick = selectId
        ? list.find((x) => x.id === selectId)
        : list.find((x) => x.status === "open") || list[0];
      if (pick) await selectReview(pick);
      else { setReview(null); setItems([]); }
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true);
      else setMsg({ ok: false, text: errorText(e, "Couldn't load access reviews.") });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadReviews(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function startReview(e) {
    e?.preventDefault();
    const name = newName.trim() || `Access review — ${new Date().toISOString().slice(0, 10)}`;
    setBusy("start");
    setMsg(null);
    try {
      const { data } = await api.post("/access-reviews/", { name });
      setNewName("");
      await loadReviews(data.id);
      setMsg({ ok: true, text: `Started "${data.name}" — every user account has been snapshotted into the grid.` });
    } catch (ex) {
      setMsg({ ok: false, text: errorText(ex, "Couldn't start the review.") });
    } finally {
      setBusy(null);
    }
  }

  async function saveItem(item, patch) {
    setSavingId(item.id);
    setMsg(null);
    try {
      const { data } = await api.patch(`/access-review-items/${item.id}/`, patch);
      setItems((prev) => prev.map((i) => (i.id === item.id ? data : i)));
      // Keep the picker's decided/total label honest without a refetch.
      const delta = (data.decision !== "pending" ? 1 : 0) - (item.decision !== "pending" ? 1 : 0);
      if (delta) {
        const reviewId = data.review ?? item.review;
        setReviews((rs) => rs.map((r) => (r.id === reviewId ? { ...r, decided_count: (r.decided_count || 0) + delta } : r)));
      }
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't save that change.") });
      return false;
    } finally {
      setSavingId(null);
    }
  }

  async function commitNote(item) {
    const draft = drafts[item.id];
    if (draft === undefined) return;
    if (draft === (item.decision_notes || "")) {
      setDrafts((d) => { const n = { ...d }; delete n[item.id]; return n; });
      return;
    }
    const ok = await saveItem(item, { decision_notes: draft });
    if (ok) setDrafts((d) => { const n = { ...d }; delete n[item.id]; return n; });
  }

  async function complete() {
    setBusy("complete");
    setMsg(null);
    try {
      const { data } = await api.post(`/access-reviews/${review.id}/complete/`);
      setReview(data);
      setReviews((rs) => rs.map((r) => (r.id === data.id ? data : r)));
      setMsg({ ok: true, text: "Review completed — the grid is now read-only evidence." });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't complete the review.") });
    } finally {
      setBusy(null);
    }
  }

  async function exportCsv() {
    setBusy("export");
    setMsg(null);
    try {
      await downloadFile(`/access-reviews/${review.id}/export/`, `access-review-${review.id}.csv`);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't export the review.") });
    } finally {
      setBusy(null);
    }
  }

  if (denied) {
    return (
      <PanelTransition>
        <Panel>
          <Empty title="Access reviews are limited to administrators and auditors.">
            Ask an administrator if you need this.
          </Empty>
        </Panel>
      </PanelTransition>
    );
  }

  const total = items.length;
  const decided = items.filter((i) => i.decision !== "pending").length;
  const pending = total - decided;
  const completed = review?.status === "completed";
  const editable = canWrite && !completed;
  const status = REVIEW_STATUS[review?.status] || REVIEW_STATUS.open;
  const allDecided = total > 0 && decided === total;

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        <StackItem className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Access review"
              className="input input-sm w-auto min-w-[240px] max-w-[360px]"
              value={review?.id || ""}
              disabled={loading || reviews.length === 0}
              onChange={(e) => {
                const r = reviews.find((x) => x.id === Number(e.target.value));
                if (r) selectReview(r);
              }}
            >
              {reviews.length === 0 ? <option value="">No reviews yet</option> : null}
              {reviews.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} — {r.status} ({r.decided_count}/{r.item_count})
                </option>
              ))}
            </select>
            {canWrite ? (
              <form className="flex flex-wrap items-center gap-2" onSubmit={startReview}>
                <input
                  aria-label="New review name"
                  className="input input-sm w-[280px]"
                  placeholder="New review name (e.g. Q3 2026 access review)"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  disabled={busy === "start"}
                />
                <Button
                  type="submit"
                  size="sm"
                  variant="primary"
                  icon={<Plus className="h-3.5 w-3.5" strokeWidth={2} />}
                  disabled={busy === "start"}
                >
                  {busy === "start" ? "Starting…" : "Start new review"}
                </Button>
              </form>
            ) : null}
          </div>

          {review ? (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                icon={<Download className="h-3.5 w-3.5" strokeWidth={2} />}
                onClick={exportCsv}
                disabled={busy === "export"}
              >
                {busy === "export" ? "Exporting…" : "Export CSV"}
              </Button>
              {editable ? (
                <Button
                  size="sm"
                  variant="primary"
                  icon={<CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} />}
                  disabled={busy === "complete" || itemsLoading || pending > 0}
                  onClick={complete}
                >
                  {busy === "complete"
                    ? "Completing…"
                    : pending > 0
                      ? `${pending} decision${pending === 1 ? "" : "s"} left`
                      : "Complete review"}
                </Button>
              ) : null}
            </div>
          ) : null}
        </StackItem>

        {msg ? (
          <StackItem>
            <div className={cn("notice", msg.ok ? "notice-ok" : "notice-err")} role={msg.ok ? "status" : "alert"}>
              {msg.text}
            </div>
          </StackItem>
        ) : null}

        {loading ? (
          <StackItem>
            <Panel><Loading /></Panel>
          </StackItem>
        ) : !review ? (
          <StackItem>
            <Panel>
              <Empty title="No access reviews yet">
                {canWrite
                  ? "Starting a review snapshots every user account — role, activity, folder grants and capabilities — into a grid. Record a decision per row, then export the CSV as audit evidence."
                  : "An administrator hasn't started one yet. Completed reviews will appear here as read-only evidence."}
              </Empty>
            </Panel>
          </StackItem>
        ) : (
          <>
            <StackItem>
              <Panel className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label>Attestation progress</Label>
                  <div className="flex items-center gap-2">
                    <Badge tone={completed || allDecided ? "success" : "muted"} mono>
                      <span className="tabular">{decided}/{total}</span> decided
                    </Badge>
                    <Badge tone={status.tone} mono dot>{status.label}</Badge>
                  </div>
                </div>
                <Meter
                  value={decided}
                  total={total}
                  tone={completed || allDecided ? "success" : "accent"}
                  className="mt-2"
                  height={8}
                  ariaLabel="Access review progress"
                />
                <p className="mt-2 text-2xs text-faint">
                  Started {fmtDate(review.created_at)}
                  {review.created_by_name ? ` by ${review.created_by_name}` : ""}
                  {review.completed_at ? ` · completed ${fmtDate(review.completed_at)}` : ""}
                  {!canWrite && !completed ? " · read-only for your role" : ""}
                </p>
              </Panel>
            </StackItem>

            <StackItem>
              <Panel className="overflow-hidden">
                <PanelHeader title={review.name} meta={`${total} users · ${decided} decided`} />
                {itemsLoading ? (
                  <Loading />
                ) : total === 0 ? (
                  <Empty title="No rows in this review">
                    The snapshot found no user accounts to attest.
                  </Empty>
                ) : (
                  <div className="overflow-x-auto">
                    <div className="min-w-[1240px]">
                      <div className={cn("grid gap-4 border-b border-line bg-surface-2 px-5 py-2", GRID)}>
                        {COLUMNS.map((h) => <Label key={h}>{h}</Label>)}
                      </div>
                      <ul className="divide-y divide-line">
                        {items.map((it, i) => {
                          const name = it.full_name || it.username;
                          const rowBusy = savingId === it.id;
                          return (
                            <motion.li
                              key={it.id}
                              initial={{ opacity: 0, y: 6 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ duration: 0.22, ease: EASE, delay: Math.min(i, 16) * 0.03 }}
                              className={cn("grid items-center gap-4 px-5 py-3", GRID)}
                            >
                              <span className="min-w-0">
                                <span className="block truncate text-[13px] font-medium text-ink">{name}</span>
                                <span className="block truncate font-mono text-2xs text-muted">
                                  <span className="text-accent">{it.username}</span>
                                  {it.email ? ` · ${it.email}` : ""}
                                </span>
                              </span>
                              <span className="min-w-0">
                                <span className="block truncate text-xs text-ink">{it.role_name || "—"}</span>
                                {it.job_title ? <span className="block truncate text-2xs text-muted">{it.job_title}</span> : null}
                              </span>
                              <span>
                                {it.is_active
                                  ? <Badge tone="success" dot mono>yes</Badge>
                                  : <Badge tone="danger" dot mono>no</Badge>}
                              </span>
                              <span className="tabular font-mono text-xs text-muted">{fmtDate(it.last_login)}</span>
                              <span className="tabular font-mono text-xs text-ink">{it.folder_grants ?? 0}</span>
                              <span className="truncate text-xs text-muted" title={it.capabilities || undefined}>
                                {it.capabilities || "—"}
                              </span>
                              <span className="flex min-w-0 flex-col items-start gap-1">
                                {editable ? (
                                  <DecisionControl
                                    item={it}
                                    disabled={rowBusy}
                                    onChange={(decision) => saveItem(it, { decision })}
                                  />
                                ) : (
                                  <Badge tone={DECISION_TONE[it.decision] || "muted"} mono dot>{it.decision}</Badge>
                                )}
                                {it.decided_by_name && it.decision !== "pending" ? (
                                  <span className="truncate text-2xs text-faint">
                                    {it.decided_by_name} · {fmtDate(it.decided_at)}
                                  </span>
                                ) : null}
                              </span>
                              {editable ? (
                                <input
                                  value={drafts[it.id] ?? it.decision_notes ?? ""}
                                  onChange={(e) => setDrafts((d) => ({ ...d, [it.id]: e.target.value }))}
                                  onBlur={() => commitNote(it)}
                                  onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                                  placeholder="Add a justification"
                                  aria-label={`Notes for ${name}`}
                                  maxLength={300}
                                  disabled={rowBusy}
                                  className="input input-sm"
                                />
                              ) : (
                                <span className="truncate text-xs text-muted" title={it.decision_notes || undefined}>
                                  {it.decision_notes || <span className="text-faint">—</span>}
                                </span>
                              )}
                            </motion.li>
                          );
                        })}
                      </ul>
                    </div>
                  </div>
                )}
              </Panel>
            </StackItem>
          </>
        )}
      </Stack>
    </PanelTransition>
  );
}
