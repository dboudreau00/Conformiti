import { cn } from "../../utils/cn.js";

// What each live counter counts, said once for a screen reader: the badge
// shows a bare number, and "Controls 44" alone does not say 44 of what.
const UNIT = { controls: "in progress", reviews: "open", risks: "open" };

/** The count pill on a tab or a menu row. Nothing for zero or no answer yet. */
export function NavCount({ kind, value, className }) {
  if (!value) return null;
  return (
    <span className={cn("tabular rounded-full bg-surface-2 px-1.5 py-0.5 font-mono text-[10.5px] leading-3 text-muted ring-1 ring-inset ring-line-strong", className)}>
      {value}
      {UNIT[kind] ? <span className="sr-only"> {UNIT[kind]}</span> : null}
    </span>
  );
}

/** A top-bar tab: a link or the Governance button. The current page is an
 * underline in the accent, not a filled pill; aria-current marks it for a link
 * and data-active for the button, which is not itself a page. */
export const TAB_CLASS = cn(
  "relative flex h-full shrink-0 items-center gap-1.5 whitespace-nowrap px-2 text-[13px] font-medium text-muted",
  "transition-colors duration-150 ease-out hover:text-ink aria-[current=page]:text-ink aria-expanded:text-ink data-[active=true]:text-ink",
  "before:absolute before:inset-x-0.5 before:inset-y-3 before:-z-10 before:rounded-lg before:bg-ink/0 before:transition-colors before:duration-150 hover:before:bg-ink/5",
  "after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:origin-left after:scale-x-0 after:rounded-t-sm after:bg-accent after:transition-transform after:duration-200 after:ease-out",
  "aria-[current=page]:after:scale-x-100 data-[active=true]:after:scale-x-100",
  "focus-visible:rounded-lg focus-visible:-outline-offset-4"
);

/** What the side menu is called: the edition name an add-on sends with the
 * signed-in user, else its plan label, else a plain "Add-on". Nothing here
 * decides whether the menu exists; it exists because navSections handed back
 * sections the top bar does not own. */
export function editionTitle(me) {
  const edition = me?.pro?.edition;
  if (typeof edition === "string" && edition.trim()) return edition.trim();
  const plan = me?.pro?.plan_label;
  return typeof plan === "string" && plan.trim() ? `Conformiti ${plan.trim()}` : "Add-on";
}
