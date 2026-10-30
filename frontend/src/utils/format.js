const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });

/** "-" for nothing, the input itself when it is not a date. Read as a local calendar day so the time zone cannot move
 * it to the day before. */
export function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : DATE_FMT.format(d);
}

export const displayName = (u) => u.full_name || u.username || `User ${u.id}`;
