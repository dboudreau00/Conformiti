import { useState } from "react";
import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

/** bars: [{label, value, tone?}] */
export function BarChart({ bars, height = 150, unit = "", tone = "accent", className, ariaLabel }) {
  const [active, setActive] = useState(null);
  const max = Math.max(...bars.map((b) => b.value), 1);
  const ticks = [0, 0.5, 1];

  return (
    <div className={cn("w-full", className)} role="img" aria-label={ariaLabel}>
      <div className="relative" style={{ height }}>
        {ticks.map((t) => (
          <div key={t} className="absolute left-0 right-0 border-t border-dashed border-line" style={{ bottom: `${t * 100}%` }} aria-hidden="true" />
        ))}
        <div className="absolute inset-0 flex items-end gap-2">
          {bars.map((bar, i) => {
            const isActive = active === bar.label;
            return (
              <div key={bar.label} className="group relative flex h-full flex-1 items-end" onMouseEnter={() => setActive(bar.label)} onMouseLeave={() => setActive(null)}>
                <motion.div
                  className="w-full rounded-t-[4px]"
                  style={{ backgroundColor: toneVar(bar.tone ?? tone, isActive ? 1 : 0.82) }}
                  initial={{ height: 0 }}
                  animate={{ height: `${(bar.value / max) * 100}%` }}
                  transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1], delay: 0.04 * i }}
                />
                <span
                  className={cn(
                    "tabular pointer-events-none absolute left-1/2 -translate-x-1/2 font-mono text-2xs text-ink",
                    "transition-opacity duration-150 ease-out",
                    isActive ? "opacity-100" : "opacity-0"
                  )}
                  style={{ bottom: `calc(${(bar.value / max) * 100}% + 6px)` }}
                >
                  {bar.value}
                  {unit}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-2 flex gap-2 border-t border-line pt-2">
        {bars.map((bar) => (
          <span
            key={bar.label}
            className={cn(
              "flex-1 truncate text-center font-mono text-2xs uppercase tracking-label transition-colors duration-150 ease-out",
              active === bar.label ? "text-ink" : "text-faint"
            )}
          >
            {bar.label}
          </span>
        ))}
      </div>
    </div>
  );
}
