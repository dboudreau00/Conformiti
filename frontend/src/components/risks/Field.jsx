import { cn } from "../../utils/cn.js";

/** Labelled form field: the child control must carry the matching `id`. */
export function Field({ id, label, className, children }) {
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {children}
    </div>
  );
}
