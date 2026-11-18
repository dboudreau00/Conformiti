import { cn } from "../../utils/cn.js";

const UNIT = { controls: "in progress", reviews: "open", risks: "open" };

export function NavCount({ kind, value, className }) {
  if (!value) return null;
  return (
    <span
      className={cn(
        "tabular rounded-full border border-line px-1.5 py-px font-mono text-[10px] leading-3 text-muted",
        className
      )}
    >
      {value}
      {UNIT[kind] ? <span className="sr-only"> {UNIT[kind]}</span> : null}
    </span>
  );
}

/** The current tab is marked by aria-current="page" (links) or data-active="true" (the Governance button). */
export const TAB_CLASS = cn(
  "relative flex h-full shrink-0 items-center gap-1.5 whitespace-nowrap px-2.5 text-sm font-semibold text-faint",
  "transition-colors duration-150 ease-out hover:text-ink aria-[current=page]:text-ink aria-expanded:text-ink data-[active=true]:text-ink",
  "before:absolute before:inset-x-0.5 before:inset-y-3 before:-z-10 before:rounded-lg before:bg-ink/0 before:transition-colors before:duration-150 hover:before:bg-ink/5",
  "after:absolute after:inset-x-2.5 after:-bottom-px after:h-0.5 after:origin-left after:scale-x-0 after:rounded-full after:bg-accent after:transition-transform after:duration-200 after:ease-out",
  "after:shadow-[0_0_12px_rgb(var(--accent)/var(--fx))]",
  "aria-[current=page]:after:scale-x-100 data-[active=true]:after:scale-x-100",
  "focus-visible:rounded-lg focus-visible:-outline-offset-4"
);

export function editionTitle(me) {
  const edition = me?.pro?.edition;
  if (typeof edition === "string" && edition.trim()) return edition.trim();
  const plan = me?.pro?.plan_label;
  return typeof plan === "string" && plan.trim() ? `Conformiti ${plan.trim()}` : "Add-on";
}
