import { useId } from "react";
import { Link, useLocation } from "react-router-dom";
import { MenuIcon, XIcon } from "lucide-react";
import { useShell, useShellNav } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { Label } from "../ui/Panel.jsx";
import { Popover } from "../ui/Popover.jsx";
import { NavCount, editionTitle } from "./NavParts.jsx";
import { NavIcon } from "./NavIcon.jsx";

/** Under 768px the tabs and the side menu do not fit, so both become this one
 * sheet under the bar, listing every section the person has: Workspace,
 * Governance, any sections an add-on adds, its foot items and Account. It is the
 * same data the wide layout draws, so nothing is reachable on a desktop that a
 * phone cannot reach. */
export function MobileMenu() {
  const { me, counts } = useShell();
  const { tabs, governance, side, foot, account } = useShellNav();
  const { pathname } = useLocation();
  const heading = useId();
  const groups = [
    { id: "workspace", label: "Workspace", items: tabs },
    { id: "governance", label: "Governance", items: governance },
    ...side,
    { id: "foot", label: editionTitle(me), items: foot },
    { id: "account", label: "Account", items: account },
  ].filter((g) => g.items.length > 0);

  return (
    <Popover
      label="Menu"
      role="group"
      align="none"
      className="static md:hidden"
      panelClassName="inset-x-0 top-full max-h-[calc(100dvh-60px)] overflow-y-auto rounded-none border-x-0 pb-2"
      trigger={(p, { open }) => (
        <button
          type="button"
          {...p}
          className={cn(
            "flex h-[34px] items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 text-[13px] font-medium text-ink",
            "transition-colors duration-150 ease-out hover:border-line-strong hover:bg-surface-2",
            open && "border-line-strong bg-surface-2"
          )}
        >
          {open ? <XIcon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" /> : <MenuIcon className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />}
          Menu
        </button>
      )}
    >
      {groups.map((group) => (
        <div key={group.id} className="px-2.5">
          <h2 id={`${heading}-${group.id}`} className="px-2 pb-1 pt-3"><Label>{group.label}</Label></h2>
          <ul aria-labelledby={`${heading}-${group.id}`}>
            {group.items.map((item) => {
              const active = pathname === item.path;
              return (
                <li key={item.id}>
                  <Link
                    to={item.path}
                    data-popover-item
                    data-autofocus={active ? "" : undefined}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex h-10 items-center gap-3 rounded-lg px-2.5 text-[14px] font-medium focus-visible:rounded-lg focus-visible:-outline-offset-2",
                      active ? "bg-accent/10 text-ink" : "text-muted hover:bg-ink/[0.05] hover:text-ink"
                    )}
                  >
                    <NavIcon name={item.icon} className={cn("h-4 w-4 shrink-0", active && "text-accent")} />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    <NavCount kind={item.badge} value={item.badge ? counts[item.badge] : undefined} />
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </Popover>
  );
}
