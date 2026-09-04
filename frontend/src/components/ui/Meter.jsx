import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

export function Meter({ value, total, tone = "accent", height = 6, delay = 0, className, ariaLabel }) {
  const pct = !total ? 0 : Math.min(100, (value / total) * 100);
  return (
    <div
      className={cn("w-full overflow-hidden rounded-full bg-grid", className)}
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel}
    >
      <motion.div
        className="h-full rounded-full"
        style={{ backgroundColor: toneVar(tone) }}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.55, ease: [0.23, 1, 0.32, 1], delay }}
      />
    </div>
  );
}

/** Stacked single-row bar — used where the parts must sum visibly.
 * segments: [{label, value, tone}] */
export function SegmentBar({ segments, total, height = 8, delay = 0, className, ariaLabel }) {
  return (
    <div className={cn("flex w-full overflow-hidden rounded-full bg-grid", className)} style={{ height }} role="img" aria-label={ariaLabel}>
      {segments.map((seg, i) => (
        <motion.div
          key={seg.label}
          className="h-full first:rounded-l-full last:rounded-r-full"
          style={{ backgroundColor: toneVar(seg.tone) }}
          initial={{ width: 0 }}
          animate={{ width: `${!total ? 0 : (seg.value / total) * 100}%` }}
          transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1], delay: delay + i * 0.06 }}
        />
      ))}
    </div>
  );
}

/** Legend rows for a SegmentBar / Donut: [{label, value, tone}] */
export function Legend({ items, className, columns = 2 }) {
  return (
    <ul className={cn("grid gap-y-1.5 gap-x-4", columns === 1 ? "grid-cols-1" : "grid-cols-2", className)}>
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: toneVar(it.tone) }} aria-hidden="true" />
          <span className="text-xs text-muted">{it.label}</span>
          <span className="tabular ml-auto font-mono text-2xs text-ink">{it.value}</span>
        </li>
      ))}
    </ul>
  );
}
