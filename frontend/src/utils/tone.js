// Tones map semantic meaning to theme tokens. Status colours (success /
// warning / danger) are deliberately NOT affected by the accent pack so they
// stay meaningful in evidence exports.

export const TONES = ["accent", "success", "warning", "danger", "info", "muted", "faint", "line-strong"];

/** Solid text colour per tone. */
export const TONE_TEXT = {
  accent: "text-accent",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
  muted: "text-muted",
  faint: "text-faint",
  "line-strong": "text-line-strong",
};

/** Low-alpha wash used behind badges and chips. */
export const TONE_WASH = {
  accent: "bg-accent/10",
  success: "bg-success/[0.12]",
  warning: "bg-warning/[0.14]",
  danger: "bg-danger/[0.14]",
  info: "bg-info/[0.12]",
  muted: "bg-muted/10",
  faint: "bg-faint/10",
  "line-strong": "bg-line-strong/20",
};

export const TONE_RING = {
  accent: "ring-accent/25",
  success: "ring-success/25",
  warning: "ring-warning/30",
  danger: "ring-danger/30",
  info: "ring-info/25",
  muted: "ring-muted/20",
  faint: "ring-faint/20",
  "line-strong": "ring-line-strong/30",
};

export const TONE_FILL = {
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  muted: "bg-muted",
  faint: "bg-faint",
  "line-strong": "bg-line-strong",
};

/** Raw CSS colour for SVG fills/strokes and inline styles — stays reactive to the active theme. */
export function toneVar(tone, alpha) {
  return alpha === undefined ? `rgb(var(--${tone}))` : `rgb(var(--${tone}) / ${alpha})`;
}

// --- Domain vocab -> tone ----------------------------------------------------
export const CONTROL_STATUS = {
  not_started: { label: "Not started", tone: "faint" },
  in_progress: { label: "In progress", tone: "warning" },
  implemented: { label: "Implemented", tone: "success" },
  not_applicable: { label: "Not applicable", tone: "line-strong" },
};

export const DOC_STATUS = {
  draft: { label: "Draft", tone: "faint" },
  in_review: { label: "In review", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  expired: { label: "Expired", tone: "danger" },
};

export const RISK_STATUS = {
  open: { label: "Open", tone: "danger" },
  mitigating: { label: "Mitigating", tone: "warning" },
  accepted: { label: "Accepted", tone: "muted" },
  closed: { label: "Closed", tone: "success" },
};

export const RISK_RATING = {
  low: "muted",
  moderate: "info",
  high: "warning",
  critical: "danger",
};

/** Tone for a review that is due in `days` (negative = overdue). */
export function dueTone(days) {
  if (days == null) return "muted";
  if (days < 0) return "danger";
  if (days <= 7) return "warning";
  if (days <= 30) return "info";
  return "success";
}

export function dueLabel(days) {
  if (days == null) return "no review";
  if (days < 0) return `${-days}d over`;
  return `${days}d`;
}

/** Readiness bands. The labels deliberately avoid "Not started" and "Not
 *  applicable": CONTROL_STATUS already uses those words, and both render as
 *  buttons on the same row. */
export const READINESS_BAND = {
  not_started: { label: "Not ready", tone: "faint" },
  at_risk: { label: "At risk", tone: "danger" },
  nearly: { label: "Nearly there", tone: "warning" },
  ready: { label: "Ready", tone: "success" },
  not_applicable: { label: "Excluded", tone: "muted" },
};
