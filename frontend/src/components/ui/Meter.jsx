import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

const GROW = { duration: 0.28, ease: [0.23, 1, 0.32, 1] };

/** A line that fills to `value` of `total` and, in the Conformiti packs, glows where it is filled. `pending` (of the
 * same total) is drawn after the fill, unlit: work under way. */
export function Meter({ value, total, pending = 0, tone = "accent", height = 6, delay = 0, className, ariaLabel }) {
  const pct = !total ? 0 : Math.max(0, Math.min(100, (value / total) * 100));
  const rest = !total ? 0 : Math.max(0, Math.min(100 - pct, (pending / total) * 100));
  return (
    <div
      className={cn("relative flex w-full rounded-full bg-grid", className)}
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel}
    >
      <motion.div
        className="relative h-full shrink-0 rounded-full"
        style={{
          "--meter-tone": `var(--${tone})`,
          backgroundColor: toneVar(tone),
          boxShadow: `0 0 10px 1px ${toneVar(tone, "var(--fx)")}, 0 0 24px 2px ${toneVar(tone, "calc(var(--fx) * 0.45)")}`,
        }}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ ...GROW, delay }}
      >
        {pct > 0 ? <span className="meter-head" aria-hidden="true" /> : null}
      </motion.div>
      {rest > 0 ? (
        <span className="h-full rounded-r-full" style={{ width: `${rest}%`, backgroundColor: toneVar(tone, 0.25) }} aria-hidden="true" />
      ) : null}
    </div>
  );
}

/** segments: [{label, value, tone}]. One segment per non-empty band, sized by its count, a hairline apart. */
export function SegmentBar({ segments, total, height = 8, delay = 0, className, ariaLabel }) {
  const drawn = segments.filter((seg) => seg.value > 0);
  return (
    <div className={cn("flex w-full gap-0.5 overflow-hidden rounded-full bg-grid", className)} style={{ height }} role="img" aria-label={ariaLabel}>
      {drawn.map((seg, i) => (
        <motion.div
          key={seg.label}
          className="h-full min-w-[6px] first:rounded-l-full last:rounded-r-full"
          style={{ backgroundColor: toneVar(seg.tone) }}
          initial={{ width: 0 }}
          animate={{ width: `${!total ? 0 : (seg.value / total) * 100}%` }}
          transition={{ ...GROW, delay: delay + i * 0.06 }}
        />
      ))}
    </div>
  );
}

/** items: [{label, value, tone}] */
export function Legend({ items, className, columns = 2 }) {
  return (
    <ul className={cn("grid gap-y-1.5 gap-x-4", columns === 1 ? "grid-cols-1" : "grid-cols-2", className)}>
      {items.map((it) => (
        <li key={it.label} className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: toneVar(it.tone) }} aria-hidden="true" />
          <span className="whitespace-nowrap text-[13px] text-muted">{it.label}</span>
          <span className="tabular ml-auto font-mono text-xs text-ink">{it.value}</span>
        </li>
      ))}
    </ul>
  );
}
