import { cn } from "../../utils/cn.js";
import { TONE_FILL, TONE_RING, TONE_TEXT, TONE_WASH } from "../../utils/tone.js";

export function Badge({ children, tone = "muted", dot = false, mono = false, className, ...rest }) {
  const t = TONE_TEXT[tone] ? tone : "muted";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-2xs font-medium ring-1",
        mono && "font-mono uppercase tracking-label",
        TONE_TEXT[t],
        TONE_WASH[t],
        TONE_RING[t],
        className
      )}
      {...rest}
    >
      {dot ? <span className={cn("h-1.5 w-1.5 rounded-full", TONE_FILL[t])} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

export function Dot({ tone = "muted", className }) {
  return <span className={cn("h-2 w-2 shrink-0 rounded-[3px]", TONE_FILL[tone] || TONE_FILL.muted, className)} aria-hidden="true" />;
}
