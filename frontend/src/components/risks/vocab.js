// Register vocabulary shared by the Risks page and its private components.
// Values mirror governance/models.py (Risk.Type / Risk.Treatment / rating bands).
import { RISK_STATUS } from "../../utils/tone.js";

export const STATUSES = Object.entries(RISK_STATUS).map(([value, meta]) => [value, meta.label]);

export const TYPES = [
  ["control_gap", "Control gap"],
  ["audit_finding", "Audit finding"],
  ["pentest", "Pen test"],
  ["vendor", "Vendor"],
  ["incident", "Incident"],
  ["other", "Other"],
];

export const TREATMENTS = [
  ["mitigate", "Mitigate"],
  ["accept", "Accept"],
  ["transfer", "Transfer"],
  ["avoid", "Avoid"],
];

export const SCALE = [1, 2, 3, 4, 5];
export const LIKELIHOOD_WORDS = ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"];
export const IMPACT_WORDS = ["Negligible", "Minor", "Moderate", "Major", "Severe"];

export const TEMPLATE_CSV =
  "Title,Description,Status,Type,Likelihood,Impact,Owner,Control,Due date,Jira,Mitigation plan,Note\n" +
  "Example: laptops missing encryption,12 laptops without disk encryption,Open,Control gap,High,High,owen,CC6.1,2026-09-15,SEC-101,Enforce via MDM,First note\n";

export const typeLabel = (v) => TYPES.find(([k]) => k === v)?.[1] || v || "—";
export const treatmentLabel = (v) => TREATMENTS.find(([k]) => k === v)?.[1] || v || "—";

/** Open or mitigating — the rows the summary counters and the heatmap describe. */
export const isLive = (r) => r.status === "open" || r.status === "mitigating";

/** Same 5×5 banding as Risk.rating on the server: 1-4 low, 5-9 moderate, 10-15 high, 16-25 critical. */
export function ratingFor(score) {
  if (score >= 16) return "critical";
  if (score >= 10) return "high";
  if (score >= 5) return "moderate";
  return "low";
}

/** Calendar days from today to an ISO date (negative = past). null when unset. */
export function daysUntil(iso) {
  if (!iso) return null;
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((new Date(y, m - 1, d) - today) / 86400000);
}

/** Register filters, in chip order. "severe" = live risks rated high or critical,
 * matching what GET /risks/summary/ counts in by_rating. */
export const FILTERS = ["live", "overdue", "severe", "closed", "all"];

export function filterRisks(risks, filter) {
  switch (filter) {
    case "all":
      return risks;
    case "overdue":
      return risks.filter((r) => r.is_overdue);
    case "severe":
      return risks.filter((r) => isLive(r) && (r.rating === "high" || r.rating === "critical"));
    case "closed":
      return risks.filter((r) => r.status === "closed");
    default:
      return risks.filter(isLive);
  }
}

/** Client-side stand-in for GET /risks/summary/ so the filter chips keep
 * working when that call fails. Same shape, same live-only semantics. */
export function deriveSummary(risks) {
  const s = { open: 0, mitigating: 0, overdue: 0, accepted: 0, closed: 0, by_rating: { low: 0, moderate: 0, high: 0, critical: 0 } };
  for (const r of risks) {
    if (r.status === "open") s.open += 1;
    else if (r.status === "mitigating") s.mitigating += 1;
    else if (r.status === "accepted") s.accepted += 1;
    else if (r.status === "closed") s.closed += 1;
    if (isLive(r)) {
      if (r.is_overdue) s.overdue += 1;
      const band = r.rating || ratingFor((r.likelihood || 0) * (r.impact || 0));
      if (band in s.by_rating) s.by_rating[band] += 1;
    }
  }
  return s;
}
