import { useEffect, useState } from "react";
import { cn } from "../../utils/cn.js";

/**
 * A page of a long list, with the rest a click away.
 *
 * A control register is a few thousand rows; rendering them all makes the
 * first paint and every filter keystroke walk the whole register, and leaves
 * a hundred screens of scroll with nothing to aim at. Returns the visible
 * slice, how many are left and the function that shows the next page; the
 * count resets whenever the filters in `resetOn` change.
 */
export function usePage(rows, size = 100, resetOn = []) {
  const [limit, setLimit] = useState(size);
  useEffect(() => {
    setLimit(size);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, resetOn);
  const visible = rows.length > limit ? rows.slice(0, limit) : rows;
  return {
    visible,
    shown: visible.length,
    remaining: Math.max(0, rows.length - limit),
    more: () => setLimit((n) => n + size),
    size,
  };
}

/**
 * A list that shows its first few rows and offers the rest on request.
 *
 * Content grows with the customer's programme (twenty-five frameworks, a few
 * thousand controls) while the screen does not, so anything rendered as a
 * flat run of rows or names needs a ceiling. `children` is a render function
 * given the number of rows to show; the toggle appears only when there are
 * more than `initial`.
 *
 *   <ShowMore total={frameworks.length} initial={8} noun="frameworks">
 *     {(n) => frameworks.slice(0, n).map(...)}
 *   </ShowMore>
 */
export function ShowMore({ total, initial = 8, noun = "rows", className, buttonClassName, children }) {
  const [open, setOpen] = useState(false);
  const hidden = Math.max(0, total - initial);
  const visible = open ? total : Math.min(initial, total);
  return (
    <div className={className}>
      {children(visible)}
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className={cn(
            "mt-2 text-xs font-medium text-accent transition-colors duration-150 ease-out hover:text-ink",
            buttonClassName
          )}
        >
          {open ? "Show fewer" : `Show all ${total} ${noun}`}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Names joined into a sentence, with a ceiling: "A, B, C and 22 more".
 * For the places a list of names is read rather than scanned.
 */
export function joinSome(names, max = 3) {
  const list = names.filter(Boolean);
  if (list.length <= max) return joinAll(list);
  const rest = list.length - max;
  return `${list.slice(0, max).join(", ")} and ${rest} more`;
}

export function joinAll(names) {
  const list = names.filter(Boolean);
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
}
