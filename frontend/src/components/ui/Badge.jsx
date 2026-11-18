import { cn } from "../../utils/cn.js";
import { TONE_FILL, TONE_RING, TONE_TEXT, TONE_WASH } from "../../utils/tone.js";

/** `glyph` (a status mark, an icon) takes the place of the dot. */
export function Badge({ children, tone = "muted", dot = false, glyph, mono = false, className, ...rest }) {
  const t = TONE_TEXT[tone] ? tone : "muted";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] text-xs font-semibold leading-4 ring-1",
        mono && "font-mono text-2xs uppercase tracking-label",
        TONE_TEXT[t],
        TONE_WASH[t],
        TONE_RING[t],
        className
      )}
      {...rest}
    >
      {glyph ?? (dot ? <span className={cn("h-1.5 w-1.5 rounded-full", TONE_FILL[t])} aria-hidden="true" /> : null)}
      {children}
    </span>
  );
}

export function Dot({ tone = "muted", className }) {
  return <span className={cn("h-2 w-2 shrink-0 rounded-[3px]", TONE_FILL[tone] || TONE_FILL.muted, className)} aria-hidden="true" />;
}
