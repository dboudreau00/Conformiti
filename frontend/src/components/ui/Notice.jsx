import { cn } from "../../utils/cn.js";

const KIND = { ok: "notice-ok", err: "notice-err", warn: "notice-warn" };

/** One result or error line. `kind` is "ok", "err" or "warn"; an error is announced at once, the others politely.
 * Pass `onDismiss` where the line should stay until the person clears it. */
export function Notice({ kind = "ok", onDismiss, className, children }) {
  return (
    <div
      role={kind === "err" ? "alert" : "status"}
      className={cn("notice", KIND[kind] || KIND.ok, onDismiss && "flex items-start justify-between gap-3", className)}
    >
      <div className="min-w-0">{children}</div>
      {onDismiss ? (
        <button type="button" className="link shrink-0" onClick={onDismiss}>
          Dismiss
        </button>
      ) : null}
    </div>
  );
}
