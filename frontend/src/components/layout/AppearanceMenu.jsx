import { motion } from "framer-motion";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { ACCENT_PACKS, THEME_PACKS, accentHex, useTheme } from "../../theme.js";
import { cn } from "../../utils/cn.js";
import { Label } from "../ui/Panel.jsx";
import { Menu, MenuItem, Popover } from "../ui/Popover.jsx";

/** Theme pack and accent, the same two choices the Settings page offers. A
 * menu of radio items: the keyboard model is the shared one, and a pick keeps
 * the panel open so a pack and an accent can be tried together. Custom colours
 * and Reset stay on the Settings page. */
export function AppearanceMenu() {
  const { theme, accent, setTheme, setAccent } = useTheme();
  const activeTheme = THEME_PACKS.find((t) => t.id === theme) ?? THEME_PACKS[2];
  const activeAccent = ACCENT_PACKS.find((a) => a.id === accent);
  const accentName = activeAccent ? activeAccent.name : "Custom";

  return (
    <Popover
      menu
      label="Appearance"
      panelClassName="sm:w-[300px]"
      trigger={(p, { open }) => (
        <button
          type="button"
          {...p}
          aria-label={`Appearance: ${activeTheme.name} theme pack, ${accentName} accent`}
          title="Appearance"
          className={cn(
            "flex h-[34px] shrink-0 items-center gap-1.5 rounded-lg border border-line bg-surface px-2 text-ink",
            "transition-colors duration-150 ease-out hover:border-line-strong hover:bg-surface-2",
            open && "border-line-strong bg-surface-2"
          )}
        >
          <span className="relative mr-1 block h-[18px] w-[18px] shrink-0" aria-hidden="true">
            <span className="flex h-full w-full overflow-hidden rounded-[5px] ring-1 ring-line-strong">
              <span className="h-full w-1/2" style={{ background: activeTheme.swatch[0] }} />
              <span className="h-full w-1/2" style={{ background: activeTheme.swatch[1] }} />
            </span>
            <span className="absolute -bottom-[5px] -right-[5px] h-2.5 w-2.5 rounded-full bg-accent ring-2 ring-surface" />
          </span>
          <ChevronDownIcon className={cn("h-3.5 w-3.5 text-muted transition-transform duration-150 ease-out", open && "rotate-180")} strokeWidth={2} aria-hidden="true" />
        </button>
      )}
    >
      <Menu label="Appearance">
        <div role="group" aria-label="Theme pack">
          <div className="border-b border-line px-3 py-2">
            <Label>Theme pack</Label>
          </div>
          <div className="p-1.5">
            {THEME_PACKS.map((pack) => (
              <MenuItem key={pack.id} radio checked={pack.id === theme} onClick={() => setTheme(pack.id)}
                        className={cn("gap-2.5 px-2", pack.id === theme && "bg-accent/10")}>
                <span className="flex h-7 w-7 shrink-0 overflow-hidden rounded-md ring-1 ring-line-strong" aria-hidden="true">
                  <span className="h-full w-1/2" style={{ background: pack.swatch[0] }} />
                  <span className="h-full w-1/2" style={{ background: pack.swatch[1] }} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-ink">{pack.name}</span>
                  <span className="block text-2xs font-normal leading-4 text-muted">{pack.blurb}</span>
                </span>
                {pack.id === theme ? <CheckIcon className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.5} aria-hidden="true" /> : null}
              </MenuItem>
            ))}
          </div>
        </div>
        <div role="group" aria-label="Accent colour">
          <div className="flex items-center justify-between border-y border-line px-3 py-2">
            <Label>Accent</Label>
            <span className="text-xs text-muted">{accentName}</span>
          </div>
          <div className="flex items-center gap-1.5 px-3.5 pb-3.5 pt-2.5" data-menu-h>
            {ACCENT_PACKS.map((a) => (
              <MenuItem
                key={a.id}
                radio
                checked={a.id === accent}
                aria-label={a.name}
                title={a.name}
                onClick={() => setAccent(a.id)}
                className="relative h-7 w-7 justify-center rounded-full p-0 hover:scale-110 hover:bg-transparent focus-visible:rounded-full focus-visible:bg-transparent focus-visible:outline-offset-4"
              >
                <span className="h-[18px] w-[18px] rounded-full" style={{ background: a.hex }} />
                {a.id === accent ? (
                  <motion.span
                    layoutId="accent-ring"
                    className="absolute inset-0 rounded-full ring-2 ring-accent ring-offset-2 ring-offset-surface"
                    transition={{ type: "spring", stiffness: 500, damping: 34 }}
                    aria-hidden="true"
                  />
                ) : null}
              </MenuItem>
            ))}
            {!activeAccent ? (
              <span className="relative flex h-7 w-7 items-center justify-center rounded-full" title="Custom accent" aria-hidden="true">
                <span className="h-[18px] w-[18px] rounded-full" style={{ background: accentHex(accent) }} />
                <span className="absolute inset-0 rounded-full ring-2 ring-accent ring-offset-2 ring-offset-surface" aria-hidden="true" />
              </span>
            ) : null}
          </div>
        </div>
      </Menu>
    </Popover>
  );
}
