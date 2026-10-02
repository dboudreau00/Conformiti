import { Link, useLocation } from "react-router-dom";
import { ChevronDownIcon } from "lucide-react";
import { navCaption } from "../../nav.js";
import { useShell, useShellNav } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { Label } from "../ui/Panel.jsx";
import { Popover } from "../ui/Popover.jsx";
import { NavCount, TAB_CLASS } from "./NavParts.jsx";
import { NavIcon } from "./NavIcon.jsx";

/** The Governance section as one tab. It opens a two-column panel of every
 * Governance page with its icon, live count and caption. When the page you
 * are on is one of them the tab is the active one and names it, so the bar
 * still says where you are with the panel closed.
 *
 * The panel hangs from the bar's lower edge rather than from the button, so
 * the root is static and the sticky header is what it is positioned against.
 * Its links take the arrow keys in reading order (a row down is two cells). */
export function GovernanceMenu() {
  const { counts } = useShell();
  const { governance } = useShellNav();
  const { pathname } = useLocation();
  if (!governance.length) return null;
  const current = governance.find((item) => item.path === pathname);

  return (
    <Popover
      label="Governance"
      role="group"
      align="none"
      className="static flex h-full min-w-0"
      panelClassName="left-3 top-full w-[704px] max-w-[calc(100vw-24px)] rounded-b-[14px] rounded-t-none"
      trigger={(p, { open }) => (
        <button type="button" {...p} data-active={!!current} className={cn(TAB_CLASS, "min-w-0 shrink")}>
          <span className="shrink-0">Governance</span>
          {current ? (
            <>
              <span className="h-3.5 w-px shrink-0 bg-line-strong" aria-hidden="true" />
              <span className="min-w-0 max-w-[160px] truncate text-ink">{current.label}</span>
            </>
          ) : null}
          <ChevronDownIcon className={cn("h-3.5 w-3.5 shrink-0 text-muted transition-transform duration-150 ease-out", open && "rotate-180")} strokeWidth={2} aria-hidden="true" />
        </button>
      )}
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <Label>Governance</Label>
        <Label>{governance.length} sections</Label>
      </div>
      <ul className="grid grid-cols-2 gap-x-2.5 gap-y-0.5 p-2" data-popover-cols="2">
        {governance.map((item) => {
          const active = item.path === pathname;
          const caption = navCaption(item.path);
          return (
            <li key={item.id}>
              <Link
                to={item.path}
                data-popover-item
                data-autofocus={active ? "" : undefined}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group grid grid-cols-[34px_minmax(0,1fr)] items-start gap-3 rounded-[10px] py-2.5 pl-2.5 pr-3",
                  "transition-colors duration-150 ease-out hover:bg-ink/[0.045] focus-visible:rounded-[10px] focus-visible:-outline-offset-2",
                  active && "bg-accent/10"
                )}
              >
                <span
                  className={cn(
                    "flex h-[34px] w-[34px] items-center justify-center rounded-[9px] transition-colors duration-150 ease-out",
                    active ? "bg-accent text-accent-ink" : "bg-surface-2 text-muted ring-1 ring-inset ring-line group-hover:text-ink"
                  )}
                >
                  <NavIcon name={item.icon} className="h-4 w-4" />
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex items-center gap-2 text-[13px] font-semibold leading-5 text-ink">
                    {item.label}
                    <NavCount kind={item.badge} value={item.badge ? counts[item.badge] : undefined} />
                  </span>
                  {caption ? <span className="text-xs leading-[1.4] text-muted">{caption}</span> : null}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="flex items-center justify-between gap-3 border-t border-line bg-surface-2 px-4 py-2 text-xs text-muted">
        <span>Settings and Sign out are in the account menu.</span>
        <span>
          <kbd className="rounded-[5px] border border-line-strong bg-surface px-1.5 font-mono text-[10.5px] leading-4">Esc</kbd> to close
        </span>
      </div>
    </Popover>
  );
}
