import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { LogOutIcon } from "lucide-react";
import { NAV_SECTIONS } from "../../nav.js";
import { useShell } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { Label } from "../ui/Panel.jsx";
import { ConformitiLogo } from "../brand/ConformitiLogo.jsx";
import { NavIcon } from "./NavIcon.jsx";

export function Sidebar({ onSignOut }) {
  const { pathname } = useLocation();
  const { me, counts } = useShell();

  return (
    <nav
      aria-label="Primary"
      className="sticky top-0 flex h-screen w-[248px] shrink-0 flex-col border-r border-line bg-surface-2 transition-colors duration-300 ease-out max-md:hidden"
    >
      <div className="px-5 py-5">
        <ConformitiLogo size={36} tagline="SOC 2 · ISO 27001 · PCI" />
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-4">
        {NAV_SECTIONS.map((section) => (
          <div key={section.id} className="mb-5">
            <Label className="mb-2 block px-2">{section.label}</Label>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const isActive = pathname === item.path;
                const badge = item.badge ? counts[item.badge] : undefined;
                return (
                  <li key={item.id}>
                    <NavLink
                      to={item.path}
                      aria-current={isActive ? "page" : undefined}
                      className={cn(
                        "group relative flex h-9 items-center gap-2.5 rounded-lg px-2.5",
                        "transition-colors duration-150 ease-out",
                        isActive ? "text-accent-ink" : "text-muted hover:bg-ink/[0.04] hover:text-ink"
                      )}
                    >
                      {isActive ? (
                        <motion.span
                          layoutId="nav-active-pill"
                          className="absolute inset-0 rounded-lg bg-accent"
                          transition={{ type: "spring", stiffness: 520, damping: 38, mass: 0.7 }}
                          aria-hidden="true"
                        />
                      ) : null}
                      <NavIcon name={item.icon} className="relative h-4 w-4 shrink-0" />
                      <span className="relative text-[13px] font-medium">{item.label}</span>
                      {badge ? (
                        <span
                          className={cn(
                            "tabular relative ml-auto rounded-full px-1.5 py-px font-mono text-2xs",
                            isActive ? "bg-accent-ink/20 text-accent-ink" : "bg-grid text-faint"
                          )}
                        >
                          {badge}
                        </span>
                      ) : null}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-line px-5 py-4">
        <p className="truncate text-[13px] font-semibold text-ink">{me?.full_name || me?.username || "…"}</p>
        <p className="truncate text-xs text-muted">{me?.role_detail?.name || (me?.is_superuser ? "Superuser" : "No role")}</p>
        <button
          type="button"
          onClick={onSignOut}
          className="mt-2.5 inline-flex items-center gap-1.5 text-xs text-muted transition-colors duration-150 ease-out hover:text-danger"
        >
          <LogOutIcon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden="true" />
          Sign out
        </button>
      </div>
    </nav>
  );
}

/** Compact horizontal nav for narrow screens (the sidebar is hidden below md). */
export function MobileNav({ onSignOut }) {
  const { pathname } = useLocation();
  const items = NAV_SECTIONS.flatMap((s) => s.items);
  return (
    <nav aria-label="Primary (compact)" className="flex items-center gap-1 overflow-x-auto border-b border-line bg-surface-2 px-3 py-2 md:hidden">
      {items.map((item) => (
        <NavLink
          key={item.id}
          to={item.path}
          aria-current={pathname === item.path ? "page" : undefined}
          title={item.label}
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            pathname === item.path ? "bg-accent text-accent-ink" : "text-muted hover:bg-ink/[0.04] hover:text-ink"
          )}
        >
          <NavIcon name={item.icon} className="h-4 w-4" />
        </NavLink>
      ))}
      <button type="button" onClick={onSignOut} className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted hover:text-danger" aria-label="Sign out">
        <LogOutIcon className="h-4 w-4" strokeWidth={1.75} />
      </button>
    </nav>
  );
}
