import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import api from "../../api/client.js";
import { errorText } from "../../utils/a11y.js";
import { cn } from "../../utils/cn.js";
import { TONE_FILL, TONE_TEXT, TONE_WASH } from "../../utils/tone.js";
import DocumentViewer from "../documents/DocumentViewer.jsx";
import { Collapse, EASE } from "../layout/PanelTransition.jsx";
import { Button, IconButton } from "../ui/Button.jsx";
import { Label, Panel } from "../ui/Panel.jsx";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** Feed `type` -> chip label + tone. Overdue items always render as danger. */
const KIND_META = {
  review_due: { label: "Review", tone: "info" },
  audit: { label: "Audit", tone: "accent" },
  task: { label: "Task", tone: "warning" },
  custom: { label: "Other", tone: "success" },
};
const KINDS = Object.keys(KIND_META);

const kindOf = (e) => KIND_META[e.type] || { label: e.type || "Event", tone: "muted" };
const eventTone = (e) => (e.overdue ? "danger" : kindOf(e).tone);

// --- Tiny local-date helpers (no date-fns). Keys are LOCAL calendar dates:
// toISOString() would shift local midnight to UTC and land events on the
// wrong cell for anyone not on UTC.
const pad = (n) => String(n).padStart(2, "0");
const localKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const monthKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
function parseKey(key) {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}
const startOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const addMonths = (d, n) => new Date(d.getFullYear(), d.getMonth() + n, 1);
/** Every day from the Monday on/before the 1st to the Sunday on/after the last. */
function monthGrid(cursor) {
  const y = cursor.getFullYear();
  const m = cursor.getMonth();
  const first = new Date(y, m, 1);
  const last = new Date(y, m + 1, 0);
  const lead = (first.getDay() + 6) % 7;
  const trail = 6 - ((last.getDay() + 6) % 7);
  return Array.from({ length: lead + last.getDate() + trail }, (_, i) => new Date(y, m, 1 - lead + i));
}
const longDate = (d) => `${DAYS_LONG[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;

/** Month calendar fed by GET /calendar/feed/ for the visible grid. Re-fetches
 * when the month changes or the parent bumps `refreshKey`. */
export function ComplianceCalendar({ refreshKey = 0, me, onChanged }) {
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const [direction, setDirection] = useState(1);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [viewing, setViewing] = useState(null);
  const [busyId, setBusyId] = useState(null);
  // What the last "Mark reviewed" came to, tied to the day it was clicked on,
  // so a refusal on the 5th never reads as one for the 12th's items.
  const [outcome, setOutcome] = useState(null);
  const reqRef = useRef(0);
  const [todayKey] = useState(() => localKey(new Date()));

  // Marking a review done needs edit access to its folder, the API returns
  // 403 otherwise, so the action is only offered to users who can manage
  // documents or folders (same rule ReviewQueue applies on the dashboard).
  const canReview = !!(me?.capabilities?.manage_documents || me?.capabilities?.manage_folders);

  const days = useMemo(() => monthGrid(cursor), [cursor]);
  const rangeStart = localKey(days[0]);
  const rangeEnd = localKey(days[days.length - 1]);

  useEffect(() => {
    const id = ++reqRef.current;
    setLoading(true);
    api
      .get(`/calendar/feed/?start=${rangeStart}&end=${rangeEnd}`)
      .then((r) => {
        if (id !== reqRef.current) return;
        setEvents(Array.isArray(r.data) ? r.data : r.data?.results || []);
        setError("");
      })
      .catch((e) => {
        if (id !== reqRef.current) return;
        // What this range holds is unknown now. The previous feed belongs to
        // another range or an older state, so it is dropped, and the counts
        // below read as unknown rather than as a confident zero.
        setEvents([]);
        setError(errorText(e, "Couldn't load the calendar feed."));
      })
      .finally(() => {
        if (id === reqRef.current) setLoading(false);
      });
  }, [rangeStart, rangeEnd, refreshKey, attempt]);

  // Audit, task and other events can only be created through the API today,
  // so most workspaces never see one; showing a chip that always empties the
  // grid is a dead control. Only chips for kinds actually present survive,
  // and a filter dropped this way is cleared rather than left hiding a grid
  // with no visible reason why. A failed load empties the feed with a visible
  // reason, so the filter survives it and applies again once a retry lands.
  const presentKinds = useMemo(() => new Set(events.map((e) => e.type)), [events]);
  useEffect(() => {
    if (filter && !error && !presentKinds.has(filter)) setFilter(null);
  }, [filter, presentKinds, error]);

  const visibleEvents = useMemo(() => (filter ? events.filter((e) => e.type === filter) : events), [events, filter]);

  const byDate = useMemo(() => {
    const map = new Map();
    for (const e of visibleEvents) {
      if (!e?.date) continue;
      const list = map.get(e.date) || [];
      list.push(e);
      map.set(e.date, list);
    }
    return map;
  }, [visibleEvents]);

  const cursorMonth = monthKey(cursor);
  const monthCount = useMemo(() => visibleEvents.filter((e) => (e.date || "").startsWith(cursorMonth)).length, [visibleEvents, cursorMonth]);
  const onCurrentMonth = cursorMonth === todayKey.slice(0, 7);
  const selectedEvents = selected ? byDate.get(selected) || [] : [];
  // The feed for this range did not arrive, so no day's count is known.
  const unknown = !!error;

  // Every change of the open day goes through here, so an outcome shown under
  // one day never carries over to another, or to the same day reopened.
  function select(key) {
    setSelected(key);
    setOutcome(null);
  }
  function move(delta) {
    setDirection(delta);
    setCursor((c) => addMonths(c, delta));
    select(null);
  }
  function goToday() {
    const next = startOfMonth(new Date());
    setDirection(next > cursor ? 1 : -1);
    setCursor(next);
    select(null);
  }

  async function markReviewed(event) {
    const name = event.title.replace(/^Review due: /, "");
    setOutcome(null);
    setBusyId(event.id);
    try {
      await api.post(`/documents/${event.document}/mark_reviewed/`);
      // The review moves the document's next review date on, so the entry has
      // left this day. It goes now: waiting for the dashboard and then the
      // feed to reload left an enabled "Mark reviewed" on a row that was
      // already attested, and a second click attested it again.
      setEvents((list) => list.filter((e) => e.id !== event.id));
      setOutcome({ day: event.date, ok: true, text: `Marked "${name}" reviewed.` });
      await onChanged?.();
    } catch (e) {
      setOutcome({ day: event.date, ok: false, text: errorText(e, `Couldn't mark "${name}" reviewed. Please try again.`) });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Panel className="flex flex-col overflow-hidden" aria-busy={loading}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Compliance calendar</h2>
          <Label>{loading ? "Loading…" : unknown ? "- items this month" : `${monthCount} ${monthCount === 1 ? "item" : "items"} this month`}</Label>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1" role="group" aria-label="Filter calendar by item type">
            {KINDS.filter((kind) => presentKinds.has(kind)).map((kind) => {
              const on = filter === kind;
              const { label, tone } = KIND_META[kind];
              return (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setFilter(on ? null : kind)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-full border px-2 py-1 font-mono text-2xs uppercase tracking-label",
                    "transition-[background-color,border-color,color] duration-150 ease-out",
                    on ? cn("border-transparent", TONE_WASH[tone], TONE_TEXT[tone]) : "border-line text-faint hover:border-line-strong hover:text-muted"
                  )}
                >
                  <span className={cn("h-1.5 w-1.5 rounded-full", TONE_FILL[tone])} aria-hidden="true" />
                  {label}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-1.5">
            {!onCurrentMonth ? (
              <Button size="sm" variant="ghost" onClick={goToday}>
                Today
              </Button>
            ) : null}
            <span className="tabular min-w-[104px] text-right text-[13px] font-medium text-ink" aria-live="polite">
              {MONTHS[cursor.getMonth()]} {cursor.getFullYear()}
            </span>
            <IconButton label="Previous month" onClick={() => move(-1)}>
              <ChevronLeftIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
            </IconButton>
            <IconButton label="Next month" onClick={() => move(1)}>
              <ChevronRightIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
            </IconButton>
          </div>
        </div>
      </header>

      {error ? (
        <div className="notice notice-err mx-5 mt-3 flex items-center justify-between gap-3" role="alert">
          <span>{error}</span>
          <Button size="sm" onClick={() => setAttempt((a) => a + 1)}>Retry</Button>
        </div>
      ) : null}

      <div className="grid grid-cols-7 border-b border-line bg-surface-2">
        {WEEKDAYS.map((d) => (
          <Label key={d} className="px-3 py-2 text-center">
            {d}
          </Label>
        ))}
      </div>

      <div className="relative overflow-hidden">
        <AnimatePresence mode="wait" initial={false} custom={direction}>
          <motion.div
            key={cursorMonth}
            custom={direction}
            initial={{ opacity: 0, x: direction * 28 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: direction * -28 }}
            transition={{ duration: 0.22, ease: EASE }}
            className="grid grid-cols-7"
          >
            {days.map((day) => {
              const key = localKey(day);
              const dayEvents = byDate.get(key) || [];
              const outside = day.getMonth() !== cursor.getMonth();
              const isToday = key === todayKey;
              const isSelected = selected === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => select(isSelected ? null : key)}
                  aria-pressed={isSelected}
                  aria-label={`${day.getDate()} ${MONTHS[day.getMonth()]} ${day.getFullYear()}, ${
                    unknown ? "items not loaded" : `${dayEvents.length} ${dayEvents.length === 1 ? "item" : "items"}`
                  }`}
                  className={cn(
                    "relative flex h-[92px] flex-col gap-1 border-b border-r border-line p-1.5 text-left",
                    "transition-colors duration-150 ease-out",
                    outside ? "bg-surface-2/60" : "bg-surface hover:bg-surface-2",
                    isSelected && "bg-accent/[0.07]"
                  )}
                >
                  <span
                    className={cn(
                      "tabular inline-flex h-5 min-w-[20px] items-center justify-center rounded-md px-1 text-xs font-medium",
                      outside && "text-faint",
                      !outside && !isToday && "text-muted",
                      isToday && "bg-accent text-accent-ink"
                    )}
                  >
                    {day.getDate()}
                  </span>
                  <span className="flex flex-col gap-1 overflow-hidden">
                    {dayEvents.slice(0, 2).map((event) => {
                      const tone = eventTone(event);
                      return (
                        <motion.span
                          key={event.id}
                          layout
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.18, ease: EASE }}
                          className={cn(
                            "flex items-center gap-1 truncate rounded px-1.5 py-0.5 text-2xs font-medium",
                            TONE_WASH[tone],
                            TONE_TEXT[tone],
                            event.completed && "line-through opacity-60"
                          )}
                          title={event.title}
                        >
                          <span className={cn("h-1 w-1 shrink-0 rounded-full", TONE_FILL[tone])} aria-hidden="true" />
                          <span className="truncate">{event.title}</span>
                        </motion.span>
                      );
                    })}
                    {dayEvents.length > 2 ? <span className="px-1.5 font-mono text-2xs text-faint">+{dayEvents.length - 2} more</span> : null}
                  </span>
                  {isSelected ? (
                    <motion.span
                      layoutId="calendar-selection"
                      className="pointer-events-none absolute inset-0 rounded-[2px] ring-2 ring-inset ring-accent"
                      transition={{ type: "spring", stiffness: 520, damping: 40 }}
                      aria-hidden="true"
                    />
                  ) : null}
                </button>
              );
            })}
          </motion.div>
        </AnimatePresence>
      </div>

      <AnimatePresence initial={false}>
        {selected ? (
          <Collapse key="day-detail" open className="bg-surface-2">
            <div className="px-5 py-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-[13px] font-semibold text-ink">{longDate(parseKey(selected))}</h3>
                <Label>{unknown ? "-" : selectedEvents.length} scheduled</Label>
              </div>
              {outcome && outcome.day === selected ? (
                <div className={cn("notice mb-2", outcome.ok ? "notice-ok" : "notice-err")} role={outcome.ok ? "status" : "alert"}>
                  {outcome.text}
                </div>
              ) : null}
              {unknown ? (
                <p className="text-xs text-muted">What is scheduled on this day could not be loaded.</p>
              ) : selectedEvents.length === 0 ? (
                <p className="text-xs text-muted">Nothing scheduled on this day.</p>
              ) : (
                <ul className="space-y-1.5">
                  {selectedEvents.map((event, i) => {
                    const tone = eventTone(event);
                    const kind = kindOf(event);
                    // A review entry is the feed's own view of a document the
                    // caller can open, named in its title. A stored event may
                    // link a document in a folder the caller cannot see, and
                    // its title is the event's, not the document's, so neither
                    // the viewer nor "Mark reviewed" is offered for one. The
                    // review_due type alone is not the test: a stored event can
                    // carry it with no document, or with one it never completes.
                    const review = event.source === "review" && event.document != null;
                    const docName = event.title.replace(/^Review due: /, "");
                    return (
                      <motion.li
                        key={event.id}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.2, ease: EASE, delay: i * 0.04 }}
                        className="flex items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2"
                      >
                        <span className={cn("h-6 w-1 shrink-0 rounded-full", TONE_FILL[tone])} aria-hidden="true" />
                        <span className="min-w-0 flex-1">
                          {review ? (
                            <button
                              type="button"
                              className={cn("block min-w-0 max-w-full truncate text-left text-[13px] font-medium text-ink hover:text-accent", event.completed && "line-through text-muted")}
                              onClick={() =>
                                setViewing({
                                  title: docName,
                                  previewUrl: `/documents/${event.document}/preview/`,
                                  downloadUrl: `/documents/${event.document}/download/`,
                                  filename: docName,
                                })
                              }
                            >
                              {event.title}
                            </button>
                          ) : (
                            <span className={cn("block truncate text-[13px] font-medium text-ink", event.completed && "line-through text-muted")}>{event.title}</span>
                          )}
                          <span className="block font-mono text-2xs uppercase tracking-label text-faint">
                            {kind.label}
                            {event.overdue ? " / overdue" : ""}
                            {event.completed ? " / completed" : ""}
                            {event.end_date && event.end_date !== event.date ? ` / until ${event.end_date}` : ""}
                          </span>
                        </span>
                        {canReview && review && !event.completed ? (
                          <Button
                            size="sm"
                            className="shrink-0"
                            disabled={busyId != null}
                            aria-label={`Mark ${docName} reviewed`}
                            onClick={() => markReviewed(event)}
                            icon={<CheckIcon className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" />}
                          >
                            {busyId === event.id ? "Marking…" : "Mark reviewed"}
                          </Button>
                        ) : null}
                        <span className="hidden text-xs text-muted sm:block">{event.assignee || "Unassigned"}</span>
                      </motion.li>
                    );
                  })}
                </ul>
              )}
            </div>
          </Collapse>
        ) : null}
      </AnimatePresence>

      <DocumentViewer open={!!viewing} {...(viewing || {})} onClose={() => setViewing(null)} />
    </Panel>
  );
}
