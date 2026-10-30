import { useMemo, useState } from "react";
import { SearchIcon } from "lucide-react";
import { Label } from "../ui/Panel.jsx";
import { cn } from "../../utils/cn.js";

function rankOf(ref, title, needle) {
  if (ref === needle) return 0;
  if (ref.startsWith(needle)) return 1;
  if (title.startsWith(needle)) return 2;
  return ref.includes(needle) || title.includes(needle) ? 3 : -1;
}

/** `controls`: rows as /control-evidence/choices/ returns them ({ id, label, title, framework, framework_name }),
 * or null while they load. `onPick(control)` receives the whole row. */
export function ControlPicker({
  controls,
  onPick,
  disabled,
  framework = "",
  placeholder = "Find a control by reference or title",
  label = "Find a control",
  limit = 40,
  className,
  id,
}) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();

  const matches = useMemo(() => {
    if (!controls || needle.length < 2) return [];
    const pool = framework ? controls.filter((c) => c.framework === framework) : controls;
    const scored = [];
    for (const c of pool) {
      const ref = String(c.label || c.control_id || "").toLowerCase();
      const title = String(c.title || "").toLowerCase();
      const rank = rankOf(ref, title, needle);
      // Rank every match before cutting to the limit, or loose matches can crowd out an exact reference.
      if (rank >= 0) scored.push([rank, c]);
    }
    scored.sort((a, b) => a[0] - b[0]);
    return scored.slice(0, limit).map(([, c]) => c);
  }, [controls, needle, framework, limit]);

  const total = controls ? (framework ? controls.filter((c) => c.framework === framework).length : controls.length) : 0;

  return (
    <div className={cn("relative", className)}>
      <label htmlFor={id} className="sr-only">{label}</label>
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
                    strokeWidth={2} aria-hidden="true" />
        <input
          id={id}
          type="search"
          className="input input-sm w-full pl-8"
          placeholder={controls ? placeholder : "Loading controls…"}
          value={q}
          disabled={disabled || !controls}
          onChange={(e) => setQ(e.target.value)}
          autoComplete="off"
        />
      </div>

      {needle.length >= 2 ? (
        matches.length ? (
          <ul className="mt-2 max-h-[240px] divide-y divide-line overflow-y-auto rounded-lg border border-line bg-surface">
            {matches.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => { onPick(c); setQ(""); }}
                  className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition-colors duration-150 ease-out hover:bg-surface-2"
                >
                  <span className="shrink-0 font-mono text-xs text-accent">{c.label || c.control_id}</span>
                  <span className="truncate text-xs text-ink">{c.title}</span>
                  {c.framework_name ? <Label className="ml-auto shrink-0">{c.framework_name}</Label> : null}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs text-muted">Nothing matches “{q.trim()}”.</p>
        )
      ) : controls ? (
        <p className="mt-1 text-2xs text-faint">
          {total.toLocaleString()} controls. Type two or more characters.
        </p>
      ) : null}
    </div>
  );
}
