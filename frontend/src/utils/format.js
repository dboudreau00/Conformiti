const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });

/** "-" for nothing, the input itself when it is not a date. Read as a local calendar day so the time zone cannot move
 * it to the day before. */
export function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : DATE_FMT.format(d);
}

/** "07 Nov 2026 14:05": the day and time as the server wrote them, like every other date here, so one moment reads
 * the same on every screen and in every export; "" for nothing, the input itself when it is not a time. */
export function fmtDateTime(iso) {
  if (!iso) return "";
  const text = String(iso);
  const time = text.slice(11, 16);
  return /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}/.test(text) ? `${fmtDate(text)} ${time}` : text;
}

/** Today as YYYY-MM-DD on the reader's own calendar; toISOString() gives the UTC day, which can be a day off. */
export function localDay(d = new Date()) {
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-");
}

export const displayName = (u) => u.full_name || u.username || `User ${u.id}`;
