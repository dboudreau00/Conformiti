import { useEffect, useState } from "react";
import { cn } from "../../utils/cn.js";

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

/** `children` is a render function given the number of rows to show. */
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
