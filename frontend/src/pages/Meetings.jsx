import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { PaperclipIcon, PlusIcon, UsersIcon, XIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { cn } from "../utils/cn.js";
import { errorText } from "../utils/a11y.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { ConfirmDialog } from "../components/ui/Dialog.jsx";
import { Meter } from "../components/ui/Meter.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";

/** cadence_status vocabulary -> badge/meter tone. Unknown values read as behind. */
const CADENCE = {
  complete: { label: "Complete", tone: "success" },
  on_track: { label: "On track", tone: "success" },
  behind: { label: "Behind", tone: "warning" },
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-07-20" -> "20 Jul 2026" without going through Date (no timezone drift). */
function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  if (!y || !m || !d || !MONTHS[m - 1]) return iso;
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`;
}

const EMPTY_SERIES = { name: "", required: "4", owner: "", description: "" };
const EMPTY_SERIES_EDIT = { name: "", required: "4", owner: "", description: "", active: true };
const EMPTY_MINUTE = { date: "", title: "", attendees: "", notes: "" };

/**
 * "Required per year" as a whole number from 1 (yearly) to 52 (weekly), or
 * null for anything else. The forms are noValidate, so min/max on the input
 * enforce nothing, and a cleared field must not quietly become some default.
 */
function parseRequired(v) {
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 && n <= 52 ? n : null;
}
const REQUIRED_RANGE = "Required per year must be a whole number from 1 to 52.";

/** What deleting a minute does to the cadence: only minutes dated this year count toward it. */
function deleteConsequence(m) {
  const year = Number(String(m?.date || "").slice(0, 4));
  if (!year) return "This cannot be undone.";
  return year === new Date().getFullYear()
    ? "It counts toward this year's cadence, so the number held this year drops by one. This cannot be undone."
    : `It is dated ${year}, so this year's cadence count does not change. This cannot be undone.`;
}

function Notice({ msg, className }) {
  if (!msg) return null;
  const ok = msg.kind === "ok";
  return (
    <div className={cn("notice", ok ? "notice-ok" : "notice-err", className)} role={ok ? "status" : "alert"}>
      {msg.text}
    </div>
  );
}

function Stat({ label, children, className }) {
  return (
    <div className={cn("min-w-0", className)}>
      <Label as="p">{label}</Label>
      <p className="tabular mt-0.5 truncate text-[17px] font-semibold leading-tight tracking-[-0.015em] text-ink">{children}</p>
    </div>
  );
}

export default function Meetings({ me }) {
  const canEdit = !!me?.capabilities?.manage_documents;

  const [series, setSeries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [activeId, setActiveId] = useState(null);
  const [minutes, setMinutes] = useState([]);
  const [minutesLoading, setMinutesLoading] = useState(false);
  const [minutesErr, setMinutesErr] = useState("");
  const [users, setUsers] = useState([]);
  const [usersErr, setUsersErr] = useState(false);

  const [showNewSeries, setShowNewSeries] = useState(false);
  const [ns, setNs] = useState(EMPTY_SERIES);
  const [seriesBusy, setSeriesBusy] = useState(false);
  const [seriesMsg, setSeriesMsg] = useState(null);

  const [editingSeries, setEditingSeries] = useState(false);
  const [es, setEs] = useState(EMPTY_SERIES_EDIT);
  const [seriesEditBusy, setSeriesEditBusy] = useState(false);
  const [seriesEditMsg, setSeriesEditMsg] = useState(null);

  const [mf, setMf] = useState(EMPTY_MINUTE);
  const [file, setFile] = useState(null);
  const fileRef = useRef(null);
  const [minuteBusy, setMinuteBusy] = useState(false);
  const [minuteMsg, setMinuteMsg] = useState(null);
  const [deletingMinute, setDeletingMinute] = useState(null);
  const [deleteMsg, setDeleteMsg] = useState(null);

  // Guards against a slow minutes response for a previously selected series overwriting the current one.
  const minutesReq = useRef(0);

  const active = series.find((s) => s.id === activeId) || null;

  async function open(id, keep = false) {
    setActiveId(id);
    if (!keep) {
      setMinutes([]);
      setMinuteMsg(null);
      setDeleteMsg(null);
      setEditingSeries(false);
    }
    const req = ++minutesReq.current;
    setMinutesLoading(true);
    setMinutesErr("");
    try {
      // Paginated at 50: follow `next` so a long-running series keeps every
      // minute (and the cadence count stays truthful).
      const rows = await fetchAll(`/meeting-minutes/?series=${id}`);
      if (req !== minutesReq.current) return;
      setMinutes([...rows].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)));
    } catch (e) {
      if (req !== minutesReq.current) return;
      setMinutesErr(errorText(e, "The minutes for this series couldn't be loaded."));
    } finally {
      if (req === minutesReq.current) setMinutesLoading(false);
    }
  }

  async function loadSeries(selectId, keep = false) {
    setLoadErr("");
    try {
      const list = await fetchAll("/meeting-series/");
      setSeries(list);
      const pick = (selectId != null && list.find((s) => s.id === selectId)) || list[0];
      if (pick) open(pick.id, keep && pick.id === selectId);
      else {
        setActiveId(null);
        setMinutes([]);
      }
    } catch (e) {
      setLoadErr(errorText(e, "Meeting cadences couldn't be loaded. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSeries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The user directory is only needed for the owner pickers on the new-series and edit-series forms.
  // A failed load is remembered so the edit form can say why its picker offers no one else.
  useEffect(() => {
    if (!canEdit) return;
    fetchAll("/users/")
      .then((list) => {
        setUsers(list);
        setUsersErr(false);
      })
      .catch(() => {
        setUsers([]);
        setUsersErr(true);
      });
  }, [canEdit]);

  function toggleNewSeries() {
    setSeriesMsg(null);
    setShowNewSeries((v) => !v);
  }

  async function addSeries(e) {
    e.preventDefault();
    if (!ns.name.trim() || seriesBusy) return;
    const required = parseRequired(ns.required);
    if (required == null) {
      setSeriesMsg({ kind: "err", text: REQUIRED_RANGE });
      return;
    }
    setSeriesBusy(true);
    setSeriesMsg(null);
    const payload = {
      name: ns.name.trim(),
      required_per_year: required,
      description: ns.description.trim(),
    };
    if (ns.owner) payload.owner = Number(ns.owner);
    try {
      const { data } = await api.post("/meeting-series/", payload);
      setNs(EMPTY_SERIES);
      setShowNewSeries(false);
      setSeriesMsg({ kind: "ok", text: `“${data.name}” created.` });
      await loadSeries(data.id);
    } catch (ex) {
      setSeriesMsg({ kind: "err", text: errorText(ex, "The series couldn't be created. Please try again.") });
    } finally {
      setSeriesBusy(false);
    }
  }

  function openEditSeries() {
    setEs({
      name: active.name,
      required: String(active.required_per_year),
      owner: active.owner ? String(active.owner) : "",
      description: active.description || "",
      active: active.active !== false,
    });
    setSeriesEditMsg(null);
    setEditingSeries(true);
  }

  async function saveSeriesEdit(e) {
    e.preventDefault();
    if (!active || seriesEditBusy || !es.name.trim()) return;
    const required = parseRequired(es.required);
    if (required == null) {
      setSeriesEditMsg({ kind: "err", text: REQUIRED_RANGE });
      return;
    }
    setSeriesEditBusy(true);
    setSeriesEditMsg(null);
    const payload = {
      name: es.name.trim(),
      required_per_year: required,
      owner: es.owner ? Number(es.owner) : null,
      description: es.description.trim(),
      active: es.active,
    };
    try {
      const { data } = await api.patch(`/meeting-series/${active.id}/`, payload);
      setEditingSeries(false);
      await loadSeries(data.id, true);
    } catch (ex) {
      setSeriesEditMsg({ kind: "err", text: errorText(ex, "The series couldn't be updated. Please try again.") });
    } finally {
      setSeriesEditBusy(false);
    }
  }

  async function addMinute(e) {
    e.preventDefault();
    if (!active || !mf.date || minuteBusy) return;
    setMinuteBusy(true);
    setMinuteMsg(null);
    setDeleteMsg(null);
    const fd = new FormData();
    fd.append("series", active.id);
    fd.append("date", mf.date);
    fd.append("title", mf.title);
    fd.append("attendees", mf.attendees);
    fd.append("notes", mf.notes);
    if (file) fd.append("file", file);
    try {
      await api.post("/meeting-minutes/", fd);
      setMf(EMPTY_MINUTE);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      setMinuteMsg({ kind: "ok", text: `Minutes recorded for ${fmtDate(mf.date)}.` });
      await loadSeries(active.id, true);
    } catch (ex) {
      setMinuteMsg({ kind: "err", text: errorText(ex, "The minutes couldn't be saved. Please try again.") });
    } finally {
      setMinuteBusy(false);
    }
  }

  // ConfirmDialog stays open on a throw and shows its message, so a failure is
  // thrown as the sentence to read, not as axios's "Request failed with status code".
  async function deleteMinute(m) {
    let alreadyGone = false;
    try {
      await api.delete(`/meeting-minutes/${m.id}/`);
    } catch (ex) {
      // A 404 means another tab or another manager deleted it first. What was
      // asked for is already true, so refresh the list instead of leaving a row
      // whose Delete can only ever fail.
      if (ex?.response?.status !== 404) throw new Error(errorText(ex, "The minutes couldn't be deleted. Please try again."));
      alreadyGone = true;
    }
    // A "Minutes recorded" notice may be describing the very record just deleted.
    setMinuteMsg(null);
    setDeleteMsg({
      kind: "ok",
      text: alreadyGone
        ? `Minutes for ${fmtDate(m.date)} had already been deleted.`
        : `Minutes for ${fmtDate(m.date)} deleted.`,
    });
    await loadSeries(m.series, true);
  }

  const activeStatus = active ? CADENCE[active.cadence_status] || CADENCE.behind : null;
  // A controlled select whose value matches no option shows its first one, "Unassigned",
  // while Save re-sends the real owner. Keep an option for the saved owner even when the
  // directory failed to load or does not list them.
  const savedOwnerMissing = !!active?.owner && !users.some((u) => u.id === active.owner);
  const detailKey = loading ? "loading" : active ? `series-${active.id}` : "none";

  return (
    <PanelTransition>
      <Stack className="grid grid-cols-12 gap-4">
        {loadErr ? (
          <StackItem className="col-span-12">
            <div className="notice notice-err flex flex-wrap items-center justify-between gap-3" role="alert">
              <span>{loadErr}</span>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setLoading(true);
                  loadSeries(activeId ?? undefined);
                }}
              >
                Retry
              </Button>
            </div>
          </StackItem>
        ) : null}

        {/* Cadence list: first in DOM (it is the navigation), on the right at desktop widths. */}
        <StackItem className="col-span-12 lg:order-2 lg:col-span-4">
          <Panel className="overflow-hidden">
            <PanelHeader title="Meeting cadences" meta={canEdit ? undefined : `${series.length} series`}>
              {canEdit ? (
                <div className="flex items-center gap-3">
                  <Label className="tabular">{series.length} series</Label>
                  <Button
                    size="sm"
                    variant={showNewSeries ? "ghost" : "primary"}
                    onClick={toggleNewSeries}
                    aria-expanded={showNewSeries}
                    aria-controls="new-series-form"
                    icon={
                      showNewSeries ? (
                        <XIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                      ) : (
                        <PlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                      )
                    }
                  >
                    {showNewSeries ? "Cancel" : "New series"}
                  </Button>
                </div>
              ) : null}
            </PanelHeader>

            <AnimatePresence initial={false}>
              {canEdit && showNewSeries ? (
                <Collapse key="new-series" open>
                  <form
                    id="new-series-form"
                    onSubmit={addSeries}
                    noValidate
                    className="space-y-3 border-b border-line bg-surface-2 p-4"
                  >
                    <Label as="p">New series</Label>
                    <div>
                      <label htmlFor="ms-name" className="field-label">
                        Name
                      </label>
                      <input
                        id="ms-name"
                        name="name"
                        className="input input-sm"
                        required
                        placeholder="e.g. Vendor Review Board"
                        value={ns.name}
                        onChange={(e) => setNs({ ...ns, name: e.target.value })}
                        autoFocus
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label htmlFor="ms-required" className="field-label">
                          Required per year
                        </label>
                        <input
                          id="ms-required"
                          name="required"
                          type="number"
                          min="1"
                          max="52"
                          inputMode="numeric"
                          className="input input-sm tabular"
                          value={ns.required}
                          onChange={(e) => setNs({ ...ns, required: e.target.value })}
                        />
                      </div>
                      {users.length > 0 ? (
                        <div>
                          <label htmlFor="ms-owner" className="field-label">
                            Owner
                          </label>
                          <select
                            id="ms-owner"
                            name="owner"
                            className="input input-sm"
                            value={ns.owner}
                            onChange={(e) => setNs({ ...ns, owner: e.target.value })}
                          >
                            <option value="">Unassigned</option>
                            {users.map((u) => (
                              <option key={u.id} value={u.id}>
                                {u.full_name || u.username}
                              </option>
                            ))}
                          </select>
                        </div>
                      ) : null}
                    </div>
                    <div>
                      <label htmlFor="ms-description" className="field-label">
                        Description
                      </label>
                      <input
                        id="ms-description"
                        name="description"
                        className="input input-sm"
                        placeholder="What this meeting covers"
                        value={ns.description}
                        onChange={(e) => setNs({ ...ns, description: e.target.value })}
                      />
                    </div>
                    <Button
                      type="submit"
                      size="sm"
                      variant="primary"
                      className="w-full"
                      disabled={seriesBusy || !ns.name.trim()}
                      icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                    >
                      {seriesBusy ? "Creating…" : "Create series"}
                    </Button>
                  </form>
                </Collapse>
              ) : null}
            </AnimatePresence>

            <Notice msg={seriesMsg} className="mx-4 mt-3" />

            {loading ? (
              <Loading>Loading cadences…</Loading>
            ) : series.length === 0 ? (
              <Empty title="No meeting cadences yet">
                {canEdit
                  ? "Create a series to start tracking how often each governance forum meets."
                  : "Nothing has been set up yet. Ask a document manager to add the first series."}
              </Empty>
            ) : (
              <ul className="divide-y divide-line">
                {series.map((s) => {
                  const st = CADENCE[s.cadence_status] || CADENCE.behind;
                  const on = s.id === activeId;
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => open(s.id)}
                        aria-current={on ? "true" : undefined}
                        className={cn(
                          "relative w-full px-5 py-3 text-left transition-colors duration-150 ease-out hover:bg-surface-2",
                          on && "bg-surface-2"
                        )}
                      >
                        {on ? (
                          <motion.span
                            layoutId="series-rail"
                            className="absolute inset-y-0 left-0 w-[2px] bg-accent"
                            transition={{ type: "spring", stiffness: 520, damping: 38 }}
                            aria-hidden="true"
                          />
                        ) : null}
                        <span className="flex items-center justify-between gap-3">
                          <span className="truncate text-[13px] font-medium text-ink">{s.name}</span>
                          <span className="flex shrink-0 items-center gap-1.5">
                            {s.active === false ? <Badge tone="faint">Inactive</Badge> : null}
                            <Badge tone={st.tone} dot>
                              {st.label}
                            </Badge>
                          </span>
                        </span>
                        <span className="mt-2 flex items-center gap-3">
                          <Meter
                            value={s.held_this_year}
                            total={s.required_per_year}
                            tone={st.tone}
                            height={5}
                            ariaLabel={`${s.held_this_year} of ${s.required_per_year} meetings held this year`}
                          />
                          <span className="tabular shrink-0 font-mono text-2xs text-faint">
                            {s.held_this_year}/{s.required_per_year} · expected {s.expected_to_date}
                          </span>
                        </span>
                        <span className="mt-1.5 block truncate text-xs text-muted">
                          Owner: {s.owner_name || <span className="text-faint">unassigned</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            <p className="border-t border-line px-5 py-3 text-xs leading-snug text-faint">
              “Expected” pro-rates the yearly requirement by the current month, so a quarterly meeting shows behind if
              fewer sessions were held than the calendar demands.
            </p>
          </Panel>
        </StackItem>

        {/* Selected series: minutes as evidence, plus the recording form for document managers. */}
        <StackItem className="col-span-12 lg:order-1 lg:col-span-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={detailKey}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: EASE }}
              className="flex flex-col gap-4"
            >
              {loading ? (
                <Panel>
                  <Loading>Loading meetings…</Loading>
                </Panel>
              ) : !active ? (
                <Panel>
                  <Empty title="No cadence selected">
                    Meeting cadences track how often each governance forum meets and keep the minutes as evidence.
                  </Empty>
                </Panel>
              ) : (
                <>
                  <Panel className="overflow-hidden">
                    <PanelHeader title={active.name}>
                      <div className="flex shrink-0 items-center gap-2">
                        {active.active === false ? <Badge tone="faint">Inactive</Badge> : null}
                        <Badge tone={activeStatus.tone} dot>
                          {activeStatus.label}
                        </Badge>
                        {canEdit ? (
                          <Button size="sm" variant="ghost" onClick={openEditSeries}>
                            Edit
                          </Button>
                        ) : null}
                      </div>
                    </PanelHeader>

                    {editingSeries ? (
                      <form onSubmit={saveSeriesEdit} noValidate className="space-y-3 border-b border-line bg-surface-2 p-4">
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                          <div>
                            <label htmlFor="es-name" className="field-label">
                              Name
                            </label>
                            <input
                              id="es-name"
                              className="input input-sm"
                              required
                              value={es.name}
                              onChange={(e) => setEs({ ...es, name: e.target.value })}
                              maxLength={160}
                              disabled={seriesEditBusy}
                            />
                          </div>
                          <div>
                            <label htmlFor="es-required" className="field-label">
                              Required per year
                            </label>
                            <input
                              id="es-required"
                              type="number"
                              min="1"
                              max="52"
                              inputMode="numeric"
                              className="input input-sm tabular"
                              value={es.required}
                              onChange={(e) => setEs({ ...es, required: e.target.value })}
                              disabled={seriesEditBusy}
                            />
                          </div>
                          <div>
                            <label htmlFor="es-owner" className="field-label">
                              Owner
                            </label>
                            <select
                              id="es-owner"
                              className="input input-sm"
                              value={es.owner}
                              onChange={(e) => setEs({ ...es, owner: e.target.value })}
                              disabled={seriesEditBusy}
                              aria-describedby={usersErr ? "es-owner-hint" : undefined}
                            >
                              <option value="">Unassigned</option>
                              {savedOwnerMissing ? (
                                <option value={String(active.owner)}>{active.owner_name || "Current owner"}</option>
                              ) : null}
                              {users.map((u) => (
                                <option key={u.id} value={u.id}>
                                  {u.full_name || u.username}
                                </option>
                              ))}
                            </select>
                            {usersErr ? (
                              <p id="es-owner-hint" className="mt-1.5 text-xs text-muted">
                                The user list couldn't be loaded, so the owner can only be kept or cleared.
                              </p>
                            ) : null}
                          </div>
                        </div>
                        <div>
                          <label htmlFor="es-description" className="field-label">
                            Description
                          </label>
                          <textarea
                            id="es-description"
                            rows={2}
                            className="input input-sm"
                            placeholder="What this meeting covers"
                            value={es.description}
                            onChange={(e) => setEs({ ...es, description: e.target.value })}
                            disabled={seriesEditBusy}
                          />
                        </div>
                        <label className="flex items-center gap-2 text-[13px] text-ink">
                          <input
                            type="checkbox"
                            checked={es.active}
                            onChange={(e) => setEs({ ...es, active: e.target.checked })}
                            disabled={seriesEditBusy}
                          />
                          This forum is still active
                        </label>
                        <Notice msg={seriesEditMsg} />
                        <div className="flex justify-end gap-2">
                          <Button type="button" size="sm" variant="ghost" onClick={() => setEditingSeries(false)} disabled={seriesEditBusy}>
                            Cancel
                          </Button>
                          <Button type="submit" size="sm" variant="primary" disabled={seriesEditBusy || !es.name.trim()}>
                            {seriesEditBusy ? "Saving…" : "Save"}
                          </Button>
                        </div>
                      </form>
                    ) : active.description ? (
                      <p className="border-b border-line px-5 py-3 text-[13px] leading-snug text-muted">{active.description}</p>
                    ) : null}

                    <div className="grid grid-cols-2 gap-4 border-b border-line bg-surface-2 px-5 py-3 md:grid-cols-4">
                      <Stat label="Held this year">{active.held_this_year}</Stat>
                      <Stat label="Expected to date">{active.expected_to_date}</Stat>
                      <Stat label="Required per year">{active.required_per_year}</Stat>
                      <Stat label="Owner" className="md:col-span-1">
                        {active.owner_name || <span className="font-normal text-faint">Unassigned</span>}
                      </Stat>
                    </div>

                    <div className="flex items-center justify-between gap-4 px-5 py-2.5">
                      <Label as="h3">Minutes</Label>
                      <Label className="tabular">
                        {minutes.length} {minutes.length === 1 ? "record" : "records"}
                      </Label>
                    </div>

                    {minutesErr ? (
                      <div className="notice notice-err mx-5 mb-4" role="alert">
                        {minutesErr}
                      </div>
                    ) : null}

                    <Notice msg={deleteMsg} className="mx-5 mb-4" />

                    {minutesLoading && minutes.length === 0 ? (
                      <Loading>Loading minutes…</Loading>
                    ) : minutes.length === 0 ? (
                      minutesErr ? null : (
                        <Empty title="No minutes recorded yet">
                          {canEdit
                            ? "Record the first meeting below; its date counts toward this year's cadence."
                            : "Minutes will appear here once a document manager records a meeting."}
                        </Empty>
                      )
                    ) : (
                      <ul
                        className={cn(
                          "divide-y divide-line border-t border-line transition-opacity duration-150 ease-out",
                          minutesLoading && "opacity-60"
                        )}
                        aria-busy={minutesLoading}
                      >
                        {minutes.map((m, i) => (
                          <motion.li
                            key={m.id}
                            initial={{ opacity: 0, x: -6 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ duration: 0.2, ease: EASE, delay: 0.05 + Math.min(i, 12) * 0.04 }}
                            className="flex flex-wrap items-start gap-x-4 gap-y-2 px-5 py-3.5 md:flex-nowrap"
                          >
                            <Badge mono className="tabular mt-0.5 shrink-0">
                              {fmtDate(m.date)}
                            </Badge>
                            <div className="min-w-0 flex-1 basis-full md:basis-auto">
                              <p className="text-[13px] font-medium text-ink">{m.title || "Meeting minutes"}</p>
                              <p className="mt-0.5 flex items-start gap-1.5 text-xs text-muted">
                                <UsersIcon className="mt-0.5 h-3 w-3 shrink-0 text-faint" strokeWidth={2} aria-hidden="true" />
                                <span className="min-w-0 break-words">
                                  {m.attendees || <span className="text-faint">Attendees not recorded</span>}
                                </span>
                              </p>
                              {m.notes ? (
                                <p className="mt-1.5 whitespace-pre-line break-words text-[13px] leading-snug text-muted">{m.notes}</p>
                              ) : null}
                              {m.created_by_name ? <Label className="mt-1.5 block">Recorded by {m.created_by_name}</Label> : null}
                            </div>
                            <div className="flex shrink-0 items-center gap-3 md:mt-0.5">
                              {m.download_url ? (
                                <button
                                  type="button"
                                  className="link"
                                  onClick={() => downloadFile(m.download_url, `${m.title || "minutes"}`)}
                                >
                                  <PaperclipIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                                  Open file
                                </button>
                              ) : null}
                              {canEdit ? (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => setDeletingMinute(m)}
                                  aria-label={`Delete the minutes of ${fmtDate(m.date)}${m.title ? `, ${m.title}` : ""}`}
                                >
                                  Delete
                                </Button>
                              ) : null}
                            </div>
                          </motion.li>
                        ))}
                      </ul>
                    )}
                  </Panel>

                  {canEdit ? (
                    <Panel className="overflow-hidden">
                      <PanelHeader title="Record minutes" meta={active.name} />
                      <form onSubmit={addMinute} noValidate className="p-5">
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <div>
                            <label htmlFor="mm-date" className="field-label">
                              Date
                            </label>
                            <input
                              id="mm-date"
                              name="date"
                              type="date"
                              required
                              className="input tabular"
                              value={mf.date}
                              onChange={(e) => setMf({ ...mf, date: e.target.value })}
                            />
                          </div>
                          <div>
                            <label htmlFor="mm-title" className="field-label">
                              Title
                            </label>
                            <input
                              id="mm-title"
                              name="title"
                              className="input"
                              placeholder="e.g. Q3 security steering"
                              value={mf.title}
                              onChange={(e) => setMf({ ...mf, title: e.target.value })}
                            />
                          </div>
                        </div>
                        <div className="mt-4">
                          <label htmlFor="mm-attendees" className="field-label">
                            Attendees
                          </label>
                          <input
                            id="mm-attendees"
                            name="attendees"
                            className="input"
                            placeholder="Names, separated by commas"
                            value={mf.attendees}
                            onChange={(e) => setMf({ ...mf, attendees: e.target.value })}
                          />
                        </div>
                        <div className="mt-4">
                          <label htmlFor="mm-notes" className="field-label">
                            Notes / decisions
                          </label>
                          <textarea
                            id="mm-notes"
                            name="notes"
                            rows={3}
                            className="input"
                            placeholder="Key points and decisions"
                            value={mf.notes}
                            onChange={(e) => setMf({ ...mf, notes: e.target.value })}
                          />
                        </div>
                        <div className="mt-4">
                          <label htmlFor="mm-file" className="field-label">
                            Attachment (optional)
                          </label>
                          <input
                            id="mm-file"
                            name="file"
                            type="file"
                            ref={fileRef}
                            onChange={(e) => setFile(e.target.files?.[0] || null)}
                            className="block w-full text-[13px] text-muted file:mr-3 file:cursor-pointer file:rounded-md file:border file:border-line file:bg-surface file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-ink hover:file:border-line-strong"
                          />
                        </div>

                        <Notice msg={minuteMsg} className="mt-4" />

                        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                          <Label>Counts toward {active.name}</Label>
                          <Button type="submit" variant="primary" disabled={minuteBusy || !mf.date}>
                            {minuteBusy ? "Saving…" : "Save minutes"}
                          </Button>
                        </div>
                      </form>
                    </Panel>
                  ) : null}
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </StackItem>
      </Stack>

      <ConfirmDialog
        open={!!deletingMinute}
        onClose={() => setDeletingMinute(null)}
        title={
          deletingMinute?.title
            ? `Delete “${deletingMinute.title}” (${fmtDate(deletingMinute.date)})?`
            : `Delete the minutes of ${fmtDate(deletingMinute?.date)}?`
        }
        description={deleteConsequence(deletingMinute)}
        confirmLabel="Delete"
        onConfirm={() => deleteMinute(deletingMinute)}
      />
    </PanelTransition>
  );
}
