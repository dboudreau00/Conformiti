import { useState } from "react";
import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

/** options: [{id, label, count?}]. With more than `collapseAfter` options only the first few and the
 * selected one show, behind a "Show N more" button. A tablist: one tab stop (the selected tab), the arrow keys,
 * Home and End move to and select a neighbour, and `controls` (the id of the panel the tabs switch) is
 * announced on the selected tab. */
export function SegmentedControl({ options, value, onChange, layoutId, ariaLabel, className, collapseAfter, controls }) {
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
  // With nothing selected among the visible tabs, the first one is the tab stop.
  const stop = shown.some((o) => o.id === value) ? value : shown[0]?.id;

  function onKeyDown(e) {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys) && e.key !== "Home" && e.key !== "End") return;
    const tabs = Array.from(e.currentTarget.querySelectorAll('[role="tab"]'));
    const from = tabs.indexOf(document.activeElement);
    if (from < 0) return;
    e.preventDefault();
    let to = from;
    if (e.key === "Home") to = 0;
    else if (e.key === "End") to = tabs.length - 1;
    else to = (from + keys[e.key] + tabs.length) % tabs.length;
    tabs[to].focus();
    if (shown[to]) onChange(shown[to].id);
  }

  // The tablist holds only tabs, so the "Show N more" button sits beside it, not inside.
  return (
    <div
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-line bg-surface-2 p-0.5",
        collapsible && open ? "max-w-full flex-wrap" : "max-w-full overflow-x-auto",
        className
      )}
    >
      <div
        role="tablist"
        aria-label={ariaLabel}
        onKeyDown={onKeyDown}
        className={cn("flex items-center gap-0.5", collapsible && open && "flex-wrap")}
      >
        {shown.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={opt.id}
              role="tab"
              aria-selected={active}
              aria-controls={active ? controls : undefined}
              tabIndex={opt.id === stop ? 0 : -1}
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
      </div>
      {collapsible ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="relative flex h-7 shrink-0 items-center rounded-md px-2.5 text-[13px] font-medium text-accent transition-colors duration-150 ease-out hover:text-ink"
        >
          {open ? "Show fewer" : `Show ${hidden} more`}
        </button>
      ) : null}
    </div>
  );
}

export function Chip({ active, onClick, tone, count, disabled, children, className }) {
  return (
    <button
      type="button"
      aria-pressed={!!active}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium disabled:cursor-default",
        "transition-[background-color,border-color,color] duration-150 ease-out",
        active ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:border-line-strong hover:text-ink",
        className
      )}
    >
      {tone ? <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: toneVar(tone) }} aria-hidden="true" /> : null}
      {children}
      {count !== undefined ? <span className="tabular font-mono text-2xs text-faint">{count}</span> : null}
    </button>
  );
}
