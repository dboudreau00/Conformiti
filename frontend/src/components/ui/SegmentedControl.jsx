import { useState } from "react";
import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";

/**
 * options: [{id, label, count?}]
 *
 * `collapseAfter`: with more options than this, only the first few (and the
 * selected one) are shown, with a "+N more" tab that opens the rest. A
 * programme with twenty-five frameworks otherwise turns the strip into a
 * five-line wall. Each label stays on one line and is cut with an ellipsis,
 * the full name in its tooltip.
 */
export function SegmentedControl({ options, value, onChange, layoutId, ariaLabel, className, collapseAfter }) {
  const [open, setOpen] = useState(false);
  const collapsible = collapseAfter && options.length > collapseAfter + 1;
  let shown = options;
  let hidden = 0;
  if (collapsible && !open) {
    shown = options.slice(0, collapseAfter);
    const selected = options.find((o) => o.id === value);
    if (selected && !shown.includes(selected)) shown = [...shown, selected];
    hidden = options.length - shown.length;
  }
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5",
        collapsible && open ? "max-w-full flex-wrap" : "max-w-full overflow-x-auto",
        className
      )}
    >
      {shown.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            role="tab"
            aria-selected={active}
            type="button"
            title={opt.label}
            onClick={() => onChange(opt.id)}
            className={cn(
              "relative flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium",
              "transition-colors duration-150 ease-out",
              active ? "text-ink" : "text-muted hover:text-ink"
            )}
          >
            {active ? (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-0 rounded-md border border-line bg-surface shadow-[0_1px_2px_rgb(0_0_0/0.06)]"
                transition={{ type: "spring", stiffness: 520, damping: 38, mass: 0.6 }}
                aria-hidden="true"
              />
            ) : null}
            <span className="relative max-w-[14rem] truncate whitespace-nowrap">{opt.label}</span>
            {opt.count !== undefined ? <span className="tabular relative font-mono text-2xs text-faint">{opt.count}</span> : null}
          </button>
        );
      })}
      {collapsible ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="relative flex h-7 shrink-0 items-center rounded-md px-2.5 text-[13px] font-medium text-accent transition-colors duration-150 ease-out hover:text-ink"
        >
          {open ? "Show fewer" : `+${hidden} more`}
        </button>
      ) : null}
    </div>
  );
}

/** Pill filter chip (status filters etc.). */
export function Chip({ active, onClick, tone, count, children, className }) {
  return (
    <button
      type="button"
      aria-pressed={!!active}
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
        "transition-[background-color,border-color,color] duration-150 ease-out",
        active ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:border-line-strong hover:text-ink",
        className
      )}
    >
      {tone ? <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: `rgb(var(--${tone}))` }} aria-hidden="true" /> : null}
      {children}
      {count !== undefined ? <span className="tabular font-mono text-2xs text-faint">{count}</span> : null}
    </button>
  );
}
