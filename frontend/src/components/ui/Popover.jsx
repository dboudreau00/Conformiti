import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { EASE } from "../layout/PanelTransition.jsx";
import { cn } from "../../utils/cn.js";

export const POP = {
  initial: { opacity: 0, y: -6, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -4, scale: 0.98 },
  transition: { duration: 0.16, ease: EASE },
};

const ITEMS = '[role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [data-popover-item]';
const CONTROLS = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const ALIGN = {
  end: "right-0 origin-top-right max-sm:fixed max-sm:inset-x-2 max-sm:top-[64px] max-sm:w-auto",
  start: "left-0 origin-top-left max-sm:fixed max-sm:inset-x-2 max-sm:top-[64px] max-sm:w-auto",
  none: "",
};

function landingTarget(panel, at) {
  const items = Array.from(panel.querySelectorAll(ITEMS));
  if (items.length) {
    if (at === "last") return items[items.length - 1];
    return panel.querySelector('[aria-checked="true"]') || panel.querySelector("[data-autofocus]") || items[0];
  }
  return panel.querySelector("[data-autofocus]") || panel.querySelector(CONTROLS) || panel;
}

/** Spread `p` from `trigger(p, { open })` onto the button. Callers mark a row [data-menu-h], a grid
 * [data-popover-cols], the landing control [data-autofocus], a non-role item [data-popover-item]. */
export function Popover({
  trigger, children, label, role, menu = false, align = "end",
  className, panelClassName, open: openProp, onOpenChange,
}) {
  const id = useId();
  const [openState, setOpenState] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : openState;
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const panelRef = useRef(null);
  const landing = useRef("first");
  const changed = useRef(onOpenChange);
  useLayoutEffect(() => {
    changed.current = onOpenChange;
  });

  const setOpen = useCallback((next) => {
    if (!controlled) setOpenState(next);
    changed.current?.(next);
  }, [controlled]);

  const close = useCallback((restoreFocus) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, [setOpen]);

  useLayoutEffect(() => {
    if (!open || !panelRef.current) return;
    landingTarget(panelRef.current, landing.current)?.focus({ preventScroll: true });
    landing.current = "first";
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      const active = document.activeElement;
      const inside = !!rootRef.current?.contains(active) || active === document.body;
      setOpen(false);
      if (inside) triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, setOpen]);

  const triggerProps = {
    ref: triggerRef,
    "aria-expanded": open,
    "aria-controls": open ? id : undefined,
    "aria-haspopup": menu ? "menu" : undefined,
    onClick: () => {
      landing.current = "first";
      setOpen(!open);
    },
    onKeyDown: (e) => {
      if (!menu || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
      e.preventDefault();
      landing.current = e.key === "ArrowUp" ? "last" : "first";
      if (open) {
        landingTarget(panelRef.current, landing.current)?.focus({ preventScroll: true });
        landing.current = "first";
      } else {
        setOpen(true);
      }
    },
  };

  function onPanelClick(e) {
    const hit = e.target.closest?.('a[href], [role="menuitem"]');
    if (hit && panelRef.current?.contains(hit)) close(true);
  }

  function onPanelKeyDown(e) {
    const panel = panelRef.current;
    if (!panel) return;
    if (e.key === "Tab" && menu) {
      e.preventDefault();
      e.stopPropagation();
      close(true);
      return;
    }
    const target = e.target;
    if (e.key === " " && target.matches?.('a[role="menuitem"]')) {
      e.preventDefault();
      target.click();
      return;
    }
    // Arrow keys belong to the items; elsewhere (text fields, tray buttons) they keep their own meaning.
    if (!(target === panel || target.closest?.(ITEMS))) return;
    const items = Array.from(panel.querySelectorAll(ITEMS)).filter((n) => !n.disabled && n.getAttribute("aria-disabled") !== "true");
    const n = items.length;
    if (!n) return;
    const at = items.indexOf(target);
    const cols = Number(target.closest?.("[data-popover-cols]")?.dataset.popoverCols) || 1;
    const row = target.closest?.("[data-menu-h]");
    const go = (i) => {
      e.preventDefault();
      items[i]?.focus();
    };
    switch (e.key) {
      case "ArrowDown":
        go(at < 0 ? 0 : at + cols < n ? at + cols : at % cols);
        break;
      case "ArrowUp":
        go(at < 0 ? n - 1 : at - cols >= 0 ? at - cols : at + cols * Math.floor((n - 1 - at) / cols));
        break;
      case "ArrowRight":
      case "ArrowLeft": {
        const step = e.key === "ArrowRight" ? 1 : -1;
        if (row) {
          const mates = items.filter((m) => row.contains(m));
          const i = mates.indexOf(target);
          e.preventDefault();
          mates[(i + step + mates.length) % mates.length]?.focus();
        } else if (cols > 1 && at >= 0) {
          go((at + step + n) % n);
        }
        break;
      }
      case "Home":
        go(0);
        break;
      case "End":
        go(n - 1);
        break;
      default:
    }
  }

  return (
    <div
      ref={rootRef}
      className={cn("relative", className)}
      // Tab out of a non-menu panel closes it. A null relatedTarget is a press on something that cannot take
      // focus, which the outside-press listener already handles.
      onBlur={(e) => {
        if (open && e.relatedTarget && !rootRef.current?.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      {trigger(triggerProps, { open })}
      <AnimatePresence>
        {open ? (
          <motion.div
            {...POP}
            ref={panelRef}
            id={id}
            role={role}
            aria-label={role ? label : undefined}
            tabIndex={-1}
            onClick={onPanelClick}
            onKeyDown={onPanelKeyDown}
            className={cn(
              "absolute top-[calc(100%+8px)] z-40 overflow-hidden rounded-xl border border-line bg-surface shadow-pop outline-none",
              ALIGN[align] ?? ALIGN.end,
              panelClassName
            )}
          >
            {children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** Wrap only the items: a header or note must sit beside the menu, not inside it. */
export function Menu({ label, className, children }) {
  return (
    <div role="menu" aria-label={label} className={className}>
      {children}
    </div>
  );
}

export function MenuItem({ as: Tag = "button", radio = false, checked, current, tone, className, children, ...rest }) {
  const props = Tag === "button" ? { type: "button" } : {};
  return (
    <Tag
      role={radio ? "menuitemradio" : "menuitem"}
      aria-checked={radio ? !!checked : undefined}
      aria-current={current ? "page" : undefined}
      tabIndex={-1}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-ink",
        "transition-colors duration-150 ease-out hover:bg-ink/[0.05] focus-visible:rounded-lg focus-visible:bg-ink/[0.05] focus-visible:-outline-offset-2",
        current && "bg-accent/10",
        tone === "danger" && "hover:text-danger focus-visible:text-danger",
        className
      )}
      {...props}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function MenuSeparator() {
  return <div role="separator" className="mx-1.5 my-1 h-px bg-line" />;
}
