import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Download, Plus, X } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button, IconButton } from "../components/ui/Button.jsx";
import { ConfirmDialog } from "../components/ui/Dialog.jsx";
import { Meter } from "../components/ui/Meter.jsx";
import { Notice } from "../components/ui/Notice.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { errorText, loadFailReason } from "../utils/a11y.js";
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
const COLUMNS = ["User", "Role", "Capabilities", "Decision", "Notes"];
const GRID = "grid-cols-[minmax(220px,1.4fr)_minmax(130px,0.9fr)_minmax(150px,1fr)_240px_minmax(200px,1fr)]";
// GRID_MIN_W is GRID's narrowest width (tracks 940px + four 16px gaps + 2 x 20px padding): change them together.
const GRID_MIN_W = "min-w-[1044px]";

function fmtDate(s) {
  return s ? s.slice(0, 10) : "never";
}

const REVIEW_KEY_STEP = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
const reviewStatus = (s) => REVIEW_STATUS[s] || REVIEW_STATUS.open;

// The tone-coloured highlight and the busy state keep this off the shared SegmentedControl, which is a tab list; a
// decision is one of three choices, so it stays a radio group with a radio group's keys.
function DecisionControl({ item, disabled, onChange }) {
  const name = item.full_name || item.username;
  const decision = item.decision;
  const radios = useRef({});
  // One tab stop: the chosen radio, or the first while none is chosen.
  const stop = DECISIONS.some((d) => d.id === decision) ? decision : DECISIONS[0].id;
  return (
    <div className="flex items-center gap-2">
      <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5" role="radiogroup" aria-label={`Decision for ${name}`}>
        {DECISIONS.map((d, i) => {
          const on = decision === d.id;
          return (
            <button
              key={d.id}
              ref={(node) => { radios.current[d.id] = node; }}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={d.id === stop ? 0 : -1}
              // Not `disabled`: a row that is saving keeps focus, so a keyboard user does not lose their place.
              aria-disabled={disabled || undefined}
              onClick={() => { if (!on && !disabled) onChange(d.id); }}
              onKeyDown={(e) => {
                const step = REVIEW_KEY_STEP[e.key];
                if (!step || disabled) return;
                e.preventDefault();
                const next = DECISIONS[(i + step + DECISIONS.length) % DECISIONS.length];
                radios.current[next.id]?.focus();
                onChange(next.id);
              }}
              className={cn(
                "relative h-6 rounded-md px-2 text-2xs font-medium transition-colors duration-150 ease-out",
                "aria-disabled:cursor-not-allowed aria-disabled:opacity-60",
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
        <IconButton label={`Reset decision for ${name} to pending`} disabled={disabled} onClick={() => onChange("pending")}>
          <X className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        </IconButton>
      )}
    </div>
  );
}

export default function UserAudit({ me }) {
  const canWrite = !!me?.capabilities?.manage_users;
  // AccessAuditPermission answers those who manage users and auditors and refuses everyone else, so the page does not ask.
  const canRead = canWrite || !!me?.capabilities?.auditor;

  const [reviews, setReviews] = useState([]);
  const [review, setReview] = useState(null);
  const [items, setItems] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState(null);
  const [denied, setDenied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(false);
  // { reason } while the last load of the reviews (or of the open review's rows) failed: that is not an empty list.
  const [loadFailed, setLoadFailed] = useState(null);
  const [itemsFailed, setItemsFailed] = useState(null);
  const [busy, setBusy] = useState(null); // "start" | "complete" | "export"
  const [savingId, setSavingId] = useState(null);
  const [confirmComplete, setConfirmComplete] = useState(false);
  // What completing a review did: { reviewId, revoked: [username], skipped: [{ username, reason }] }.
  const [report, setReport] = useState(null);
  const loadSeq = useRef(0);

  async function selectReview(rev) {
    const seq = ++loadSeq.current;
    setReview(rev);
    setMsg(null);
    setDrafts({});
    setItemsFailed(null);
    setItemsLoading(true);
    try {
      const r = await api.get(`/access-review-items/?review=${rev.id}`);
      if (seq !== loadSeq.current) return;
      setItems(r.data.results || r.data);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setItems([]);
      setItemsFailed({ reason: loadFailReason(e) });
    } finally {
      if (seq === loadSeq.current) setItemsLoading(false);
    }
  }

  async function loadReviews(selectId) {
    setLoadFailed(null);
    try {
      const list = await fetchAll("/access-reviews/");
      setReviews(list);
      const pick = selectId
        ? list.find((x) => x.id === selectId)
        : list.find((x) => x.status === "open") || list[0];
      if (pick) await selectReview(pick);
      else { setReview(null); setItems([]); }
    } catch (e) {
      if (e?.response?.status === 403) setDenied(true);
      else {
        loadSeq.current += 1;
        setReviews([]);
        setReview(null);
        setItems([]);
        setItemsFailed(null);
        setItemsLoading(false);
        setLoadFailed({ reason: loadFailReason(e) });
      }
    } finally {
      setLoading(false);
    }
  }

  function retryReviews() {
    setLoading(true);
    loadReviews();
  }

  useEffect(() => { if (canRead) loadReviews(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function startReview(e) {
    e?.preventDefault();
    const name = newName.trim() || `Access review: ${new Date().toISOString().slice(0, 10)}`;
    setBusy("start");
    setMsg(null);
    try {
      const { data } = await api.post("/access-reviews/", { name });
      setNewName("");
      await loadReviews(data.id);
      setMsg({ kind: "ok", text: `Created "${data.name}".` });
    } catch (ex) {
      setMsg({ kind: "err", text: errorText(ex, "Couldn't create the review.") });
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
      const delta = (data.decision !== "pending" ? 1 : 0) - (item.decision !== "pending" ? 1 : 0);
      if (delta) {
        const reviewId = data.review ?? item.review;
        setReviews((rs) => rs.map((r) => (r.id === reviewId ? { ...r, decided_count: (r.decided_count || 0) + delta } : r)));
      }
      return true;
    } catch (e) {
      setMsg({ kind: "err", text: errorText(e, "Couldn't save that change.") });
      return false;
    } finally {
      setSavingId(null);
    }
  }

  function clearDraft(id) {
    setDrafts((d) => {
      const rest = { ...d };
      delete rest[id];
      return rest;
    });
  }

  async function commitNote(item) {
    const draft = drafts[item.id];
    if (draft === undefined) return;
    if (draft === (item.decision_notes || "")) {
      clearDraft(item.id);
      return;
    }
    const ok = await saveItem(item, { decision_notes: draft });
    if (ok) clearDraft(item.id);
  }

  async function complete() {
    setBusy("complete");
    setMsg(null);
    try {
      const { data } = await api.post(`/access-reviews/${review.id}/complete/`);
      // Completing reports the Revoke rows it would not touch; that report is recorded nowhere else, so it stays on screen.
      const { applied, ...rev } = data;
      setReview(rev);
      setReviews((rs) => rs.map((r) => (r.id === rev.id ? rev : r)));
      setReport({ reviewId: rev.id, revoked: applied?.revoked || [], skipped: applied?.skipped || [] });
    } catch (e) {
      setMsg({ kind: "err", text: errorText(e, "Couldn't complete the review.") });
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
      setMsg({ kind: "err", text: errorText(e, "Couldn't export the review.") });
    } finally {
      setBusy(null);
    }
  }

  if (denied || !canRead) {
    return (
      <PanelTransition>
        <Panel>
          <Empty title="Access reviews are restricted" />
        </Panel>
      </PanelTransition>
    );
  }

  const total = items.length;
  const decided = items.filter((i) => i.decision !== "pending").length;
  const pending = total - decided;
  const completed = review?.status === "completed";
  const editable = canWrite && !completed;
  const status = reviewStatus(review?.status);
  const allDecided = total > 0 && decided === total;
  const reviewDates = review
    ? [
        `Started ${fmtDate(review.created_at)}${review.created_by_name ? ` by ${review.created_by_name}` : ""}`,
        review.completed_at ? `Completed ${fmtDate(review.completed_at)}` : null,
      ].filter(Boolean).join(" · ")
    : "";
  const revoking = items.filter((i) => i.decision === "revoke");
  const isOwnRow = (it) => it.user != null && it.user === me?.id;
  // The server never revokes the reviewer's own access, so that row does not count toward what completing will change.
  const deactivating = revoking.filter((i) => !isOwnRow(i));

  let completeDescription;
  if (deactivating.length) {
    completeDescription = "Accounts marked Revoke are deactivated and signed out. Decisions become read-only.";
  } else if (revoking.length) {
    completeDescription = "No account is deactivated: your own row is the only one marked Revoke. Decisions become read-only.";
  } else {
    completeDescription = "No row is marked Revoke, so no account changes. Decisions become read-only.";
  }

  return (
    <PanelTransition>
      {/* Completing also deactivates accounts and revokes their refresh tokens, so the dialog names them. The rows it
          leaves alone are listed on screen afterwards. */}
      <ConfirmDialog
        open={confirmComplete}
        onClose={() => setConfirmComplete(false)}
        title="Complete this review?"
        description={completeDescription}
        confirmLabel="Complete review"
        tone={deactivating.length ? "danger-solid" : "primary"}
        onConfirm={complete}
      >
        {revoking.length ? (
          <>
            <Label className="block">Marked Revoke ({revoking.length})</Label>
            <ul className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto text-[13px] text-ink">
              {revoking.map((it) => (
                <li key={it.id} className="truncate">
                  {it.full_name || it.username}{" "}
                  <span className="font-mono text-2xs text-muted">{it.username}</span>
                  {isOwnRow(it) ? <span className="text-2xs text-muted"> (your account, skipped)</span> : null}
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </ConfirmDialog>
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
                  {r.name}, {reviewStatus(r.status).label} ({r.decided_count}/{r.item_count})
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
                  icon={<Plus className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                  disabled={busy === "start"}
                >
                  {busy === "start" ? "Creating…" : "Create review"}
                </Button>
              </form>
            ) : null}
          </div>

          {review ? (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                icon={<Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                onClick={exportCsv}
                disabled={busy === "export"}
              >
                {busy === "export" ? "Exporting…" : "Export CSV"}
              </Button>
              {editable ? (
                <Button
                  size="sm"
                  variant="primary"
                  icon={<CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                  disabled={busy === "complete" || itemsLoading || !!itemsFailed || pending > 0}
                  onClick={() => setConfirmComplete(true)}
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
            <Notice kind={msg.kind} onDismiss={() => setMsg(null)}>{msg.text}</Notice>
          </StackItem>
        ) : null}

        {report && report.reviewId === review?.id ? (
          <StackItem>
            <Notice kind={report.skipped.length ? "warn" : "ok"} onDismiss={() => setReport(null)}>
              <p className="font-medium">Review completed.</p>
              <p className="mt-1">
                {report.revoked.length
                  ? `Deactivated and signed out of every session: ${report.revoked.join(", ")}.`
                  : report.skipped.length
                    ? "No account was deactivated."
                    : "No row was marked Revoke, so no account changed."}
              </p>
              {report.skipped.length ? (
                <>
                  <p className="mt-1">Marked Revoke but left as they were, so check each by hand:</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {report.skipped.map((s, i) => (
                      <li key={`${s.username}-${i}`}><span className="font-mono">{s.username}</span>: {s.reason}</li>
                    ))}
                  </ul>
                </>
              ) : null}
            </Notice>
          </StackItem>
        ) : null}

        {loading ? (
          <StackItem>
            <Panel><Loading /></Panel>
          </StackItem>
        ) : loadFailed ? (
          <StackItem>
            <Panel>
              <LoadError what="The access reviews" reason={loadFailed.reason} onRetry={retryReviews} />
            </Panel>
          </StackItem>
        ) : !review ? (
          <StackItem>
            <Panel>
              <Empty title="No access reviews yet" />
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
                {!canWrite && !completed ? <p className="mt-2 text-2xs text-faint">Read-only for your role.</p> : null}
              </Panel>
            </StackItem>

            <StackItem>
              <Panel className="overflow-hidden">
                <PanelHeader
                  title={review.name}
                  meta={<Label className="whitespace-normal text-right">{reviewDates}</Label>}
                />
                {itemsLoading ? (
                  <Loading />
                ) : itemsFailed ? (
                  <LoadError what="The review rows" reason={itemsFailed.reason} onRetry={() => selectReview(review)} />
                ) : total === 0 ? (
                  <Empty title="No rows in this review" />
                ) : (
                  <div className="overflow-x-auto" role="region" aria-label={`Users in ${review.name}`} tabIndex={0}>
                    <div className={GRID_MIN_W} role="table">
                      <div role="rowgroup">
                        <div role="row" className={cn("grid gap-4 border-b border-line bg-surface-2 px-5 py-2", GRID)}>
                          {COLUMNS.map((h) => <Label key={h} role="columnheader">{h}</Label>)}
                        </div>
                      </div>
                      <div role="rowgroup" className="divide-y divide-line">
                        {items.map((it, i) => {
                          const name = it.full_name || it.username;
                          const rowBusy = savingId === it.id;
                          const activity = `${it.is_active ? "active" : "inactive"} · last login ${fmtDate(it.last_login)}`;
                          const grants = it.folder_grants ?? 0;
                          return (
                            <motion.div
                              key={it.id}
                              role="row"
                              initial={{ opacity: 0, y: 6 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ duration: 0.22, ease: EASE, delay: Math.min(i, 16) * 0.03 }}
                              className={cn("grid items-center gap-4 px-5 py-3", GRID)}
                            >
                              <div role="cell" className="min-w-0">
                                <span className="block truncate text-[13px] font-medium text-ink">{name}</span>
                                <span className="block truncate font-mono text-2xs text-muted">
                                  <span className="text-accent">{it.username}</span>
                                  {it.email ? ` · ${it.email}` : ""}
                                </span>
                                <span className="block truncate font-mono text-2xs text-muted" title={activity}>
                                  {activity}
                                </span>
                              </div>
                              <div role="cell" className="min-w-0">
                                <span className="block truncate text-xs text-ink">{it.role_name || "-"}</span>
                                {it.job_title ? <span className="block truncate text-2xs text-muted">{it.job_title}</span> : null}
                              </div>
                              <div role="cell" className="min-w-0">
                                <span className="block truncate text-xs text-muted" title={it.capabilities || undefined}>
                                  {it.capabilities || "-"}
                                </span>
                                <span className="block truncate text-2xs text-faint">
                                  {grants} folder grant{grants === 1 ? "" : "s"}
                                </span>
                              </div>
                              <div role="cell" className="flex min-w-0 flex-col items-start gap-1">
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
                              </div>
                              <div role="cell" className="min-w-0">
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
                                  <span className="block truncate text-xs text-muted" title={it.decision_notes || undefined}>
                                    {it.decision_notes || <span className="text-faint">-</span>}
                                  </span>
                                )}
                              </div>
                            </motion.div>
                          );
                        })}
                      </div>
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
