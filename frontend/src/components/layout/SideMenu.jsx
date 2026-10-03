import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { ChevronsLeftIcon, ChevronsRightIcon, GemIcon } from "lucide-react";
import { useShell, useShellNav } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { Label } from "../ui/Panel.jsx";
import { NavCount, editionTitle } from "./NavParts.jsx";
import { NavIcon } from "./NavIcon.jsx";

const K_RAIL = "nav.side.rail";
const K_SEEN = "nav.side.seen";
// Below this width a 240px menu would leave the page too little, so the rail
// is used whatever was chosen.
const NARROW = "(max-width: 1099px)";

const store = {
  get(k) { try { return window.localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { window.localStorage.setItem(k, v); } catch { /* a convenience only */ } },
};

function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const sync = () => setNarrow(query.matches);
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);
  return narrow;
}

function SideItem({ item, pathname, rail, counts }) {
  const active = pathname === item.path;
  return (
    <li>
      <NavLink
        to={item.path}
        aria-current={active ? "page" : undefined}
        aria-label={rail ? item.label : undefined}
        title={rail ? item.label : undefined}
        className={cn(
          "relative flex h-7 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium transition-colors duration-150 ease-out",
          rail && "mx-auto w-[38px] justify-center px-0",
          active ? "text-accent-ink" : "text-muted hover:bg-ink/[0.05] hover:text-ink"
        )}
      >
        {active ? (
          // Travels only when the page changes: left to measure on every
          // render, collapsing the menu would slide it across the rail.
          <motion.span
            layoutId="nav-active-pill"
            layoutDependency={pathname}
            className="absolute inset-0 rounded-lg bg-accent"
            transition={{ type: "spring", stiffness: 520, damping: 38, mass: 0.7 }}
            aria-hidden="true"
          />
        ) : null}
        <NavIcon name={item.icon} className="relative h-4 w-4 shrink-0" />
        {rail ? null : <span className="relative min-w-0 flex-1 truncate">{item.label}</span>}
        {rail ? null : <NavCount kind={item.badge} value={item.badge ? counts[item.badge] : undefined} className={cn("relative", active && "bg-accent-ink/20 text-accent-ink ring-0")} />}
      </NavLink>
    </li>
  );
}

/** The left menu. It holds only what the top bar does not: every section
 * beyond Workspace, Governance and Account (an add-on's sections), and the
 * items an add-on appends to Account, which sit at the foot. A core-only
 * install and an external auditor have none of that, so there is no menu, no
 * rail and no reserved width. Collapses to an icon rail (kept per browser) and is a rail below
 * 1100px; under 768px it is part of the Menu sheet instead. */
export function SideMenu() {
  const { me, counts } = useShell();
  const { side, foot } = useShellNav();
  const { pathname } = useLocation();
  const narrow = useNarrow();
  const [pref, setPref] = useState(() => store.get(K_RAIL) === "1");
  const present = side.length > 0 || foot.length > 0;

  // Until /users/me/ answers there is no way to know whether the menu exists,
  // and drawing it only then shifts the whole page sideways. The last answer
  // is remembered so the space is held while it is asked.
  useEffect(() => {
    if (me) store.set(K_SEEN, present ? "1" : "0");
  }, [me, present]);

  const rail = pref || narrow;
  const width = rail ? "w-[60px]" : "w-[240px]";
  if (!me) return store.get(K_SEEN) === "1" ? <div className={cn("hidden shrink-0 md:block", width)} aria-hidden="true" /> : null;
  if (!present) return null;

  const title = editionTitle(me);
  const toggle = () => {
    const next = !pref;
    setPref(next);
    store.set(K_RAIL, next ? "1" : "0");
  };

  return (
    <aside
      aria-label={title}
      className={cn(
        "sticky top-[60px] hidden h-[calc(100dvh-60px)] shrink-0 flex-col overflow-hidden border-r border-line md:flex",
        "bg-surface-2 bg-gradient-to-b from-accent/[0.08] to-transparent to-[190px]",
        "transition-[width,background-color] duration-200 ease-out",
        width
      )}
    >
      <div className={cn("flex min-h-[62px] items-center gap-2.5 border-b border-line", rail ? "flex-col justify-center gap-1.5 px-0 py-3" : "py-3.5 pl-3.5 pr-2.5")}>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-accent/[0.14] text-accent ring-1 ring-inset ring-accent/35" aria-hidden="true">
          <GemIcon className="h-4 w-4" strokeWidth={1.75} />
        </span>
        {rail ? null : (
          <div className="min-w-0 leading-[1.15]">
            <Label className="block text-muted">Edition</Label>
            <strong className="block truncate text-sm font-semibold tracking-[-0.01em] text-ink">{title}</strong>
          </div>
        )}
        {narrow ? null : (
          <button
            type="button"
            onClick={toggle}
            aria-label={pref ? "Expand menu" : "Collapse menu"}
            title={pref ? "Expand menu" : "Collapse menu"}
            className={cn(
              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-transparent text-muted",
              "transition-colors duration-150 ease-out hover:border-line hover:bg-surface hover:text-ink",
              !rail && "ml-auto"
            )}
          >
            {pref ? <ChevronsRightIcon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" /> : <ChevronsLeftIcon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />}
          </button>
        )}
      </div>

      {side.length ? (
        <nav aria-label={`${title} features`} className="flex-1 overflow-y-auto overflow-x-hidden pb-1.5 pt-1">
          {side.map((section, i) => (
            <div key={section.id} className={cn("px-2.5", rail && i > 0 && "mt-1.5 border-t border-line pt-1.5")}>
              {rail ? <h2 className="sr-only">{section.label}</h2> : <h2 className="px-2 pb-1 pt-2.5"><Label>{section.label}</Label></h2>}
              <ul>
                {section.items.map((item) => <SideItem key={item.id} item={item} pathname={pathname} rail={rail} counts={counts} />)}
              </ul>
            </div>
          ))}
        </nav>
      ) : null}

      {foot.length ? (
        // At the foot under a menu of sections; straight under the head when
        // the foot is all there is (an add-on that has no sections to show).
        <nav aria-label={`${title} account`} className={cn("px-2.5 py-1.5", side.length > 0 && "border-t border-line")}>
          <ul>
            {foot.map((item) => <SideItem key={item.id} item={item} pathname={pathname} rail={rail} counts={counts} />)}
          </ul>
        </nav>
      ) : null}
    </aside>
  );
}
