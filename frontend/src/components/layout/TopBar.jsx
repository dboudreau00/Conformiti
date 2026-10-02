import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { SearchIcon } from "lucide-react";
import NotificationBell from "../NotificationBell.jsx";
import { useShell, useShellNav } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { ConformitiLogo } from "../brand/ConformitiLogo.jsx";
import { AppearanceMenu } from "./AppearanceMenu.jsx";
import { GovernanceMenu } from "./GovernanceMenu.jsx";
import { MobileMenu } from "./MobileMenu.jsx";
import { NavCount, TAB_CLASS } from "./NavParts.jsx";
import { SearchPalette } from "./SearchPalette.jsx";
import { UserMenu, workspaceNote } from "./UserMenu.jsx";

// The shortcut a person's own keyboard calls it.
const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || "");

/** The one bar: the product, the Workspace tabs and Governance on the left;
 * search, appearance, the demo and version chip, the bell and the person on
 * the right. The page's title is not here, it opens the page (PanelTransition).
 *
 * Primary is the landmark an add-on finds its logo through. Its first child
 * is the link holding the mark: a white-label painter hides the first thing
 * in that link which draws the mark and puts the customer's own in front. */
export function TopBar({ onSignOut }) {
  const { pathname } = useLocation();
  const { me, health, counts } = useShell();
  const { tabs, governance } = useShellNav();
  const [searching, setSearching] = useState(false);
  const note = workspaceNote(me);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearching((was) => !was);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <header className="sticky top-0 z-30 flex h-[60px] items-center gap-2.5 border-b border-line bg-surface/85 pl-3 pr-3 backdrop-blur-xl transition-colors duration-300 ease-out min-[1061px]:pl-[18px] min-[1061px]:pr-4">
        <nav aria-label="Primary" className="flex h-full min-w-0 items-center gap-2">
          <Link to="/" className="flex shrink-0 items-center rounded-lg">
            <span aria-hidden="true" className="flex">
              <ConformitiLogo size={32} className="max-[939px]:[&>div]:hidden" />
            </span>
            <span className="sr-only">Home</span>
          </Link>
          <MobileMenu />
          <ul className="hidden h-full min-w-0 items-center md:flex">
            {tabs.map((item) => {
              const active = pathname === item.path;
              return (
                <li key={item.id} className="flex h-full">
                  <Link to={item.path} aria-current={active ? "page" : undefined} className={TAB_CLASS}>
                    <span>{item.label}</span>
                    <NavCount kind={item.badge} value={item.badge ? counts[item.badge] : undefined} />
                  </Link>
                </li>
              );
            })}
            {governance.length ? (
              <li className="flex h-full min-w-0">
                <GovernanceMenu />
              </li>
            ) : null}
          </ul>
        </nav>

        <div className="flex flex-1 items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={() => setSearching(true)}
            aria-haspopup="dialog"
            aria-keyshortcuts="Control+K Meta+K"
            title={`Search (${MAC ? "Cmd" : "Ctrl"} K)`}
            className={cn(
              "flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-muted",
              "transition-colors duration-150 ease-out hover:border-line-strong hover:bg-surface-2 hover:text-ink",
              "min-[1181px]:mx-1 min-[1181px]:w-[150px] min-[1181px]:min-w-[150px] min-[1181px]:max-w-[360px] min-[1181px]:flex-1 min-[1181px]:justify-start min-[1181px]:gap-2 min-[1181px]:px-2.5 min-[1181px]:text-left"
            )}
          >
            <SearchIcon className="h-[15px] w-[15px] shrink-0" strokeWidth={1.75} aria-hidden="true" />
            <span className="sr-only min-[1181px]:not-sr-only min-[1181px]:min-w-0 min-[1181px]:flex-1 min-[1181px]:truncate min-[1181px]:text-[12.5px]">
              Jump to a control, document or person
            </span>
            <kbd className="hidden shrink-0 rounded-md border border-line-strong bg-surface-2 px-1.5 font-mono text-[10px] font-medium leading-4 text-muted min-[1181px]:inline-block" aria-hidden="true">
              {MAC ? "Cmd K" : "Ctrl K"}
            </kbd>
          </button>

          <AppearanceMenu />

          {note ? (
            <span
              className={cn(
                "hidden max-w-[150px] shrink-0 truncate rounded-md border px-2 py-1 font-mono text-[10px] font-medium uppercase tracking-[0.06em] min-[1181px]:block",
                note.switched ? "border-warning/40 text-warning" : "border-line text-muted"
              )}
              title={note.title}
              data-testid="workspace-name"
            >
              {note.text}
            </span>
          ) : null}

          {/* The version keeps its own case: a release is named by a lower-case
              revision letter (0.9.5k), and "V0.9.5K" matched neither
              /api/health/ nor the tags. */}
          {health?.demo_accounts || health?.version ? (
            <span className="hidden h-[34px] shrink-0 flex-col justify-center rounded-md border border-line px-2.5 font-mono text-[10px] uppercase leading-[13px] tracking-[0.06em] text-muted min-[941px]:flex">
              {health?.demo_accounts ? (
                <span>
                  Demo data
                  {health?.version ? <span className="sr-only">, </span> : null}
                </span>
              ) : null}
              {health?.version ? <span className="normal-case tracking-[0.04em]">{"v" + health.version}</span> : null}
            </span>
          ) : null}

          <NotificationBell />
          <UserMenu onSignOut={onSignOut} />
        </div>
      </header>
      {/* Outside the header on purpose: its backdrop blur makes it the
          containing block for anything fixed inside it, and the dialog's
          overlay must cover the viewport, not a 60px strip. */}
      <SearchPalette open={searching} onClose={() => setSearching(false)} />
    </>
  );
}
