import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { InfoIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";

const EDGE = 8;

export function InfoTip({ label = "More about this", children, align = "left", className }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const wrap = useRef(null);
  const box = useRef(null);
  const visible = open || pinned;

  // Keeps the box inside the viewport: on a phone it would otherwise widen the page and scroll it sideways.
  const place = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const side = align === "right" ? "marginRight" : "marginLeft";
    el.style[side] = "";
    const r = el.getBoundingClientRect();
    if (!r.width) return;
    const width = document.documentElement.clientWidth;
    let shift = 0;
    if (r.right > width - EDGE) shift = width - EDGE - r.right;
    if (r.left + shift < EDGE) shift = EDGE - r.left;
    if (shift) el.style[side] = `${align === "right" ? -shift : shift}px`;
  }, [align]);

  useLayoutEffect(() => {
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [place]);

  useLayoutEffect(() => {
    if (visible) place();
  }, [visible, place]);

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
        className="flex h-6 w-6 items-center justify-center rounded-full text-faint transition-colors duration-150 ease-out hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <InfoIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
      </button>
      <span
        ref={box}
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
