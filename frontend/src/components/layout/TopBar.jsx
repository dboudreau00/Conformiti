import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { NAV_LOOKUP } from "../../nav.js";
import { useShell } from "../../shell.js";
import { ACCENT_PACKS, THEME_PACKS, accentHex, useTheme } from "../../theme.js";
import { cn } from "../../utils/cn.js";
import { Label } from "../ui/Panel.jsx";
import NotificationBell from "../NotificationBell.jsx";

export const POP = {
  initial: { opacity: 0, y: -6, scale: 0.98 },
  animate: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -4, scale: 0.98 },
  transition: { duration: 0.16, ease: [0.23, 1, 0.32, 1] },
};

export function TopBar() {
  const { pathname } = useLocation();
  const { health } = useShell();
  const { theme, accent, setTheme, setAccent } = useTheme();
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  const meta = NAV_LOOKUP[pathname] ?? { title: "Conformiti", caption: "" };
  const activeTheme = THEME_PACKS.find((t) => t.id === theme) ?? THEME_PACKS[2];
  const customAccent = accent.startsWith("#");

  useEffect(() => {
    function onDown(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => setOpen(false), [pathname]);

  return (
    <header className="sticky top-0 z-30 flex h-[60px] items-center gap-4 border-b border-line bg-surface/85 px-6 backdrop-blur-xl transition-colors duration-300 ease-out">
      <div className="min-w-0 flex-1 overflow-hidden">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
          >
            <h1 className="truncate text-[17px] font-semibold tracking-[-0.015em] text-ink">{meta.title}</h1>
            <p className="truncate text-xs text-muted">{meta.caption}</p>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Theme pack picker */}
      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-haspopup="menu"
          className="flex h-8 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-ink transition-colors duration-150 ease-out hover:border-line-strong hover:bg-surface-2"
        >
          <span className="flex h-4 w-4 overflow-hidden rounded-[4px] ring-1 ring-line-strong" aria-hidden="true">
            <span className="h-full w-1/2" style={{ background: activeTheme.swatch[0] }} />
            <span className="h-full w-1/2" style={{ background: activeTheme.swatch[1] }} />
          </span>
          <span className="hidden font-medium sm:inline">{activeTheme.name}</span>
          <ChevronDownIcon className={cn("h-3.5 w-3.5 text-muted transition-transform duration-150 ease-out", open && "rotate-180")} strokeWidth={2} aria-hidden="true" />
        </button>
        <AnimatePresence>
          {open ? (
            <motion.div {...POP} role="menu" className="absolute right-0 top-[calc(100%+8px)] w-[268px] origin-top-right overflow-hidden rounded-xl border border-line bg-surface shadow-pop">
              <div className="border-b border-line px-3 py-2">
                <Label>Theme pack</Label>
              </div>
              <ul className="p-1.5">
                {THEME_PACKS.map((pack) => (
                  <li key={pack.id}>
                    <button
                      type="button"
                      role="menuitemradio"
                      aria-checked={pack.id === theme}
                      onClick={() => setTheme(pack.id)}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors duration-150 ease-out",
                        pack.id === theme ? "bg-accent/10" : "hover:bg-surface-2"
                      )}
                    >
                      <span className="flex h-7 w-7 shrink-0 overflow-hidden rounded-md ring-1 ring-line-strong" aria-hidden="true">
                        <span className="h-full w-1/2" style={{ background: pack.swatch[0] }} />
                        <span className="h-full w-1/2" style={{ background: pack.swatch[1] }} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-medium text-ink">{pack.name}</span>
                        <span className="block truncate text-2xs text-muted">{pack.blurb}</span>
                      </span>
                      {pack.id === theme ? <CheckIcon className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.5} aria-hidden="true" /> : null}
                    </button>
                  </li>
                ))}
              </ul>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      {/* Accent pack */}
      <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Accent colour">
        {ACCENT_PACKS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="radio"
            aria-checked={a.id === accent}
            aria-label={a.name}
            title={a.name}
            onClick={() => setAccent(a.id)}
            className="relative flex h-6 w-6 items-center justify-center rounded-full transition-transform duration-150 ease-out hover:scale-110"
          >
            <span className="h-4 w-4 rounded-full" style={{ background: a.hex }} />
            {a.id === accent ? (
              <motion.span
                layoutId="accent-ring"
                className="absolute inset-0 rounded-full ring-2 ring-accent ring-offset-2 ring-offset-surface"
                transition={{ type: "spring", stiffness: 500, damping: 34 }}
                aria-hidden="true"
              />
            ) : null}
          </button>
        ))}
        {customAccent ? (
          <span className="relative flex h-6 w-6 items-center justify-center rounded-full" title="Custom accent" aria-label="Custom accent">
            <span className="h-4 w-4 rounded-full" style={{ background: accentHex(accent) }} />
            <span className="absolute inset-0 rounded-full ring-2 ring-accent ring-offset-2 ring-offset-surface" aria-hidden="true" />
          </span>
        ) : null}
      </div>

      <Label className="hidden rounded-md border border-line px-2 py-1 lg:inline-block">
        {health?.demo_accounts ? "Demo data · v" + (health?.version || "") : health?.version ? "v" + health.version : ""}
      </Label>

      <NotificationBell />
    </header>
  );
}
