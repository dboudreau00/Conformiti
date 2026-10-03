import { Link, useLocation } from "react-router-dom";
import { LogOutIcon } from "lucide-react";
import { useShell, useShellNav } from "../../shell.js";
import { cn } from "../../utils/cn.js";
import { Menu, MenuItem, MenuSeparator, Popover } from "../ui/Popover.jsx";
import { NavIcon } from "./NavIcon.jsx";

/** The workspace a person is working in, or null where naming it tells them
 * nothing: an installation with only the default workspace, where a label
 * reading "Default" would be an empty-looking section. A superuser who has switched
 * into another organisation's workspace is always told. */
export function workspaceNote(me) {
  const ws = me?.active_workspace || me?.workspace_detail;
  const switched = !!me?.active_workspace?.switched;
  if (!ws?.name || (!switched && (!ws.slug || ws.slug === "default"))) return null;
  return {
    switched,
    text: `${switched ? "Viewing " : "Workspace · "}${ws.name}`,
    title: switched ? `Switched into ${ws.slug}, not your own workspace` : "The workspace you are working in",
  };
}

function initialsOf(name) {
  const parts = name.split(/\s+/).filter((p) => /[\p{L}\p{N}]/u.test(p));
  if (!parts.length) return "?";
  const first = Array.from(parts[0])[0];
  const last = parts.length > 1 ? Array.from(parts[parts.length - 1])[0] : "";
  return (first + last).toUpperCase();
}

/** The person: name and role on the button, Settings and Sign out in the
 * menu. Below 1240px the role goes, below 1180px the name too, and the avatar
 * stays. */
export function UserMenu({ onSignOut }) {
  const { me } = useShell();
  const { account } = useShellNav();
  const { pathname } = useLocation();
  const name = me?.full_name || me?.username || "…";
  const role = me?.role_detail?.name || (me?.is_superuser ? "Superuser" : "No role");
  const note = workspaceNote(me);

  return (
    <Popover
      menu
      label="Account"
      panelClassName="sm:w-[232px]"
      trigger={(p, { open }) => (
        <button
          type="button"
          {...p}
          aria-label={`Account: ${name}, ${role}`}
          className={cn(
            "flex h-10 shrink-0 items-center gap-2 rounded-[10px] border border-transparent py-0 pl-1 pr-1 text-left",
            "transition-colors duration-150 ease-out hover:border-line hover:bg-surface-2",
            "min-[1181px]:pr-2.5",
            open && "border-line bg-surface-2"
          )}
        >
          <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full bg-accent/[0.14] font-mono text-[11px] font-medium tracking-[0.02em] text-ink ring-1 ring-inset ring-accent/35" aria-hidden="true">
            {initialsOf(name)}
          </span>
          <span className="hidden min-w-0 flex-col leading-[1.2] min-[1181px]:flex" aria-hidden="true">
            <span className="max-w-[140px] truncate text-[13px] font-semibold text-ink">{name}</span>
            <span className="hidden max-w-[140px] truncate text-[11.5px] text-muted min-[1241px]:block">{role}</span>
          </span>
        </button>
      )}
    >
      <div className="border-b border-line px-3.5 pb-2.5 pt-3">
        <p className="truncate text-[13px] font-semibold text-ink">{name}</p>
        <p className="truncate text-xs text-muted">{role}</p>
        {note ? (
          <p className={cn("mt-1.5 truncate text-2xs font-medium uppercase tracking-[0.08em]", note.switched ? "text-warning" : "text-muted")} title={note.title}>
            {note.text}
          </p>
        ) : null}
      </div>
      <Menu label="Account" className="p-1.5">
        {account.map((item) => (
          <MenuItem key={item.id} as={Link} to={item.path} current={pathname === item.path}>
            <NavIcon name={item.icon} className="h-4 w-4 shrink-0 text-muted" />
            {item.label}
          </MenuItem>
        ))}
        {account.length ? <MenuSeparator /> : null}
        <MenuItem tone="danger" onClick={onSignOut}>
          <LogOutIcon className="h-4 w-4 shrink-0 text-muted" strokeWidth={1.75} aria-hidden="true" />
          Sign out
        </MenuItem>
      </Menu>
    </Popover>
  );
}
