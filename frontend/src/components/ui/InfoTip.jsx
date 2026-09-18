import { useEffect, useId, useRef, useState } from "react";
import { InfoIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";

/**
 * A small "i" that explains a figure on request rather than at first glance.
 *
 * The text box opens while the pointer rests on the icon, or while the icon
 * has keyboard focus, and closes the moment either ends, or on Escape. A tap
 * toggles it for touch screens, and a tap anywhere else closes it. The box
 * takes no pointer events itself, so sliding the mouse onto it does not hold
 * it open. `label` is what a screen reader announces for the icon; the
 * children are the explanation, read as its description while open.
 *
 *   <Label>Readiness score</Label>
 *   <InfoTip label="How the readiness score is worked out">
 *     The mean score across every applicable control.
 *   </InfoTip>
 */
export function InfoTip({ label = "More about this", children, align = "left", className }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const wrap = useRef(null);
  const visible = open || pinned;

  useEffect(() => {
    if (!pinned) return undefined;
    const away = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setPinned(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [pinned]);

  return (
    <span
      ref={wrap}
      className={cn("relative inline-flex shrink-0", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-expanded={visible}
        aria-describedby={visible ? id : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false);
          setPinned(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            setPinned(false);
          }
        }}
        onClick={() => setPinned((v) => !v)}
        className="flex h-5 w-5 items-center justify-center rounded-full text-faint transition-colors duration-150 ease-out hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <InfoIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
      </button>
      <span
        role="tooltip"
        id={id}
        aria-hidden={!visible}
        className={cn(
          "pointer-events-none absolute top-full z-30 mt-1.5 w-max max-w-[36ch] rounded-lg border border-line bg-surface px-3 py-2",
          "text-left font-sans text-xs font-normal normal-case leading-snug tracking-normal text-muted",
          "shadow-[0_8px_24px_rgb(0_0_0/0.18)] transition-[opacity,transform] duration-150 ease-out",
          align === "right" ? "right-0" : "left-0",
          visible ? "translate-y-0 opacity-100" : "-translate-y-1 opacity-0"
        )}
      >
        {children}
      </span>
    </span>
  );
}
