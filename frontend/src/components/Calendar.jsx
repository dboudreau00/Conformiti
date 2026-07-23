import { useMemo, useState } from "react";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["January","February","March","April","May","June",
  "July","August","September","October","November","December"];

// Compact month calendar. `events` = [{date:'YYYY-MM-DD', title, type, overdue}].
export default function Calendar({ events = [] }) {
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); return d; });

  const byDate = useMemo(() => {
    const m = {};
    for (const e of events) (m[e.date] ||= []).push(e);
    return m;
  }, [events]);

  const cells = useMemo(() => {
    const year = cursor.getFullYear(), month = cursor.getMonth();
    const first = new Date(year, month, 1);
    // Monday-first offset
    const offset = (first.getDay() + 6) % 7;
    const start = new Date(year, month, 1 - offset);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    // Key cells by their LOCAL calendar date. Using toISOString() here would
    // convert local midnight to UTC and shift the key by a day for anyone not
    // on UTC, so events (keyed 'YYYY-MM-DD') would land on the wrong cell.
    const localISO = (dt) =>
      `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start); d.setDate(start.getDate() + i);
      const iso = localISO(d);
      return {
        iso, day: d.getDate(),
        out: d.getMonth() !== month,
        today: d.getTime() === today.getTime(),
        events: byDate[iso] || [],
      };
    });
  }, [cursor, byDate]);

  const shift = (n) => setCursor((c) => new Date(c.getFullYear(), c.getMonth() + n, 1));

  return (
    <div>
      <div className="cal-head">
        <div className="cal-title">{MONTHS[cursor.getMonth()]} {cursor.getFullYear()}</div>
        <div className="cal-nav" style={{ display: "flex", gap: 6 }}>
          <button onClick={() => shift(-1)} aria-label="Previous month">‹</button>
          <button onClick={() => setCursor(() => { const d = new Date(); d.setDate(1); return d; })} aria-label="Today">•</button>
          <button onClick={() => shift(1)} aria-label="Next month">›</button>
        </div>
      </div>
      <div className="cal-grid">
        {DOW.map((d) => <div key={d} className="cal-dow">{d.toUpperCase()}</div>)}
        {cells.map((c) => (
          <div key={c.iso} className={"cal-cell" + (c.out ? " out" : "") + (c.today ? " today" : "")}>
            <div className="cal-daynum">{c.day}</div>
            {c.events.slice(0, 3).map((e, i) => (
              <div key={i} className={`cal-ev ${e.type}${e.overdue ? " overdue" : ""}`} title={e.title}>
                {e.title}
              </div>
            ))}
            {c.events.length > 3 && (
              <div className="cal-daynum" style={{ marginTop: 2 }}>+{c.events.length - 3} more</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
