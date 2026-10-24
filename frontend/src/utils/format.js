// Formatting helpers that more than one screen needs, so a date or a person
// reads the same way wherever it appears.

const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });

/** "2026-07-20" (or an ISO timestamp) as "20 Jul 2026"; "-" for nothing; the
 *  input itself when it is not a date. Read as a local calendar day so the
 *  zone cannot move it to the day before. */
export function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : DATE_FMT.format(d);
}

/** How a user is named in a pick-list: full name, else username, else the id. */
export const displayName = (u) => u.full_name || u.username || `User ${u.id}`;
