import { useId, useLayoutEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

// Drawn until the box has been measured.
const FIRST_WIDTH = 320;

/** points: [{label, value}]. The graphic is drawn in the pixels it occupies, so a dot stays round, and each label
 * sits in the same column as its dot. The spoken name always carries the values; showValues also prints each one,
 * with its unit, under its label. */
export function TrendLine({ points, tone = "accent", height = 96, className, ariaLabel, showValues = false, unit = "" }) {
  const fillId = `trend-fill-${useId().replace(/:/g, "")}`;
  const box = useRef(null);
  const [w, setW] = useState(FIRST_WIDTH);
  const h = height;
  const pad = 8;
  const pts = points && points.length ? points : [];
  const max = Math.max(...pts.map((p) => p.value), 1) * 1.15;
  const cell = w / (pts.length || 1);
  const spoken = [ariaLabel, pts.map((p) => `${p.label} ${p.value}${unit}`).join(", ")].filter(Boolean).join(": ") || "No data";

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const read = () => {
      const next = Math.round(el.getBoundingClientRect().width);
      if (next > 0) setW(next);
    };
    read();
    if (typeof ResizeObserver === "undefined") return undefined;
    const watch = new ResizeObserver(read);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);

  const coords = pts.map((p, i) => ({
    x: (i + 0.5) * cell,
    y: h - pad - (p.value / max) * (h - pad * 2),
    ...p,
  }));

  const line = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" ");
  const area = coords.length > 1 ? `${line} L ${coords[coords.length - 1].x} ${h} L ${coords[0].x} ${h} Z` : "";

  return (
    <div ref={box} className={cn("w-full", className)}>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full overflow-visible" style={{ height }} role="img" aria-label={spoken}>
        <defs>
          <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={toneVar(tone)} stopOpacity="0.28" />
            <stop offset="1" stopColor={toneVar(tone)} stopOpacity="0" />
          </linearGradient>
        </defs>
        {area ? (
          <motion.path
            d={area}
            fill={`url(#${fillId})`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1], delay: 0.2 }}
          />
        ) : null}
        {coords.length > 1 ? (
          <motion.path
            d={line}
            fill="none"
            stroke={toneVar(tone)}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ filter: `drop-shadow(0 0 6px ${toneVar(tone, "var(--fx)")})` }}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
          />
        ) : null}
        {/* The latest month is the one marked: ringed in the page colour so it stands off the line. */}
        {coords.length ? (
          <motion.circle
            cx={coords[coords.length - 1].x}
            cy={coords[coords.length - 1].y}
            r={4}
            fill={toneVar(tone)}
            stroke={toneVar("bg")}
            strokeWidth={2}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1], delay: 0.6 }}
          />
        ) : null}
      </svg>
      <div className="mt-1 grid" style={{ gridTemplateColumns: `repeat(${pts.length || 1}, minmax(0, 1fr))` }} aria-hidden="true">
        {pts.map((p, i) => (
          <span key={`${p.label}-${i}`} className="whitespace-nowrap text-center font-mono text-[10px] text-faint">
            {p.label}
            {showValues ? <span className="tabular block text-muted">{`${p.value}${unit}`}</span> : null}
          </span>
        ))}
      </div>
    </div>
  );
}
