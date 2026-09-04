import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

/** points: [{label, value}] — renders a filled line; a single point renders as a marker. */
export function TrendLine({ points, tone = "accent", height = 96, className, ariaLabel }) {
  const w = 320;
  const h = height;
  const pad = 8;
  const pts = points && points.length ? points : [];
  const max = Math.max(...pts.map((p) => p.value), 1) * 1.15;
  const step = pts.length > 1 ? (w - pad * 2) / (pts.length - 1) : 0;

  const coords = pts.map((p, i) => ({
    x: pts.length > 1 ? pad + i * step : w / 2,
    y: h - pad - (p.value / max) * (h - pad * 2),
    ...p,
  }));

  const line = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" ");
  const area = coords.length > 1 ? `${line} L ${coords[coords.length - 1].x} ${h} L ${coords[0].x} ${h} Z` : "";

  return (
    <div className={cn("w-full", className)}>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height }} preserveAspectRatio="none" role="img" aria-label={ariaLabel}>
        {area ? (
          <motion.path d={area} fill={toneVar(tone, 0.1)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1], delay: 0.2 }} />
        ) : null}
        {coords.length > 1 ? (
          <motion.path
            d={line}
            fill="none"
            stroke={toneVar(tone)}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
          />
        ) : null}
        {coords.map((c, i) => (
          <motion.circle
            key={`${c.label}-${i}`}
            cx={c.x}
            cy={c.y}
            r={i === coords.length - 1 ? 3.5 : 2.5}
            fill={toneVar(i === coords.length - 1 ? tone : "surface")}
            stroke={toneVar(tone)}
            strokeWidth={1.5}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1], delay: 0.3 + i * 0.05 }}
          />
        ))}
      </svg>
      <div className="mt-1 flex justify-between">
        {pts.map((p, i) => (
          <span key={`${p.label}-${i}`} className="font-mono text-2xs uppercase tracking-label text-faint">
            {p.label}
          </span>
        ))}
      </div>
    </div>
  );
}
