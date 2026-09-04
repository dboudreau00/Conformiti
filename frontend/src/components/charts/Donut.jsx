import { useState } from "react";
import { motion } from "framer-motion";
import { toneVar } from "../../utils/tone.js";

function polar(cx, cy, r, angle) {
  const rad = ((angle - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx, cy, r, start, end) {
  const span = Math.min(end - start, 359.99);
  const from = polar(cx, cy, r, start);
  const to = polar(cx, cy, r, start + span);
  const largeArc = span > 180 ? 1 : 0;
  return `M ${from.x} ${from.y} A ${r} ${r} 0 ${largeArc} 1 ${to.x} ${to.y}`;
}

/** slices: [{label, value, tone}] */
export function Donut({ slices, size = 168, thickness = 18, centerValue, centerLabel, onActiveChange, activeLabel }) {
  const [hovered, setHovered] = useState(null);
  const active = activeLabel !== undefined ? activeLabel : hovered;
  const total = slices.reduce((sum, s) => sum + s.value, 0) || 1;
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;

  let cursor = 0;
  const arcs = slices
    .filter((s) => s.value > 0)
    .map((slice) => {
      const sweep = (slice.value / total) * 360;
      const path = arcPath(cx, cy, r, cursor + 0.6, cursor + sweep - 0.6);
      cursor += sweep;
      return { ...slice, path };
    });
  const activeSlice = arcs.find((a) => a.label === active);

  function setActive(label) {
    setHovered(label);
    onActiveChange?.(label);
  }

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} role="img" aria-label={`${centerValue} ${centerLabel}`}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={toneVar("grid")} strokeWidth={thickness} />
        {arcs.map((arc, i) => (
          <motion.path
            key={arc.label}
            d={arc.path}
            fill="none"
            stroke={toneVar(arc.tone)}
            strokeWidth={thickness}
            strokeLinecap="butt"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: active && active !== arc.label ? 0.28 : 1 }}
            transition={{
              pathLength: { duration: 0.65, ease: [0.23, 1, 0.32, 1], delay: 0.06 * i },
              opacity: { duration: 0.18, ease: [0.23, 1, 0.32, 1] },
            }}
            onMouseEnter={() => setActive(arc.label)}
            onMouseLeave={() => setActive(null)}
            className="cursor-default"
          />
        ))}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="tabular text-2xl font-semibold tracking-[-0.02em] text-ink">{activeSlice ? activeSlice.value : centerValue}</span>
        <span className="mt-0.5 max-w-[86px] text-center font-mono text-2xs uppercase tracking-label text-faint">
          {activeSlice ? activeSlice.label : centerLabel}
        </span>
      </div>
    </div>
  );
}

/** Donut + interactive legend with percentages, laid out side by side. */
export function DonutLegend({ slices, centerValue, centerLabel, size = 168 }) {
  const [active, setActive] = useState(null);
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <Donut slices={slices} size={size} centerValue={centerValue} centerLabel={centerLabel} activeLabel={active} onActiveChange={setActive} />
      <ul className="min-w-[180px] flex-1 space-y-2">
        {slices.map((s) => (
          <li
            key={s.label}
            onMouseEnter={() => setActive(s.label)}
            onMouseLeave={() => setActive(null)}
            className={`flex items-center gap-2.5 rounded-md px-1 py-0.5 transition-opacity duration-150 ${active && active !== s.label ? "opacity-40" : ""}`}
          >
            <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: toneVar(s.tone) }} aria-hidden="true" />
            <span className="text-[13px] text-ink">{s.label}</span>
            <span className="tabular ml-auto font-mono text-2xs text-faint">{Math.round((s.value / total) * 100)}%</span>
            <span className="tabular w-8 text-right font-mono text-[13px] font-medium text-ink">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
