import { cn } from "../../utils/cn.js";

export function Panel({ children, className, padded = false, as: Tag = "section", ...rest }) {
  return (
    <Tag
      className={cn(
        "rounded-panel border border-line bg-surface shadow-panel",
        "transition-colors duration-300 ease-out",
        padded && "p-5",
        className
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function PanelHeader({ title, meta, children, className }) {
  return (
    <header className={cn("flex items-center justify-between gap-4 border-b border-line px-5 py-3.5", className)}>
      <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
      {meta ? <Label>{meta}</Label> : null}
      {children}
    </header>
  );
}

export function Label({ children, className, as: Tag = "span", ...rest }) {
  return (
    <Tag className={cn("whitespace-nowrap font-mono text-2xs uppercase tracking-label text-faint", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function Divider({ className }) {
  return <div className={cn("h-px w-full bg-line", className)} />;
}

/** Centered empty state used inside panels and tables. */
export function Empty({ title, children, className }) {
  return (
    <div className={cn("px-5 py-12 text-center", className)}>
      {title ? <p className="text-[13px] font-medium text-ink">{title}</p> : null}
      {children ? <p className="mt-1 text-xs text-muted">{children}</p> : null}
    </div>
  );
}

export function Loading({ children = "Loading…", className }) {
  return (
    <div className={cn("px-5 py-10 text-center font-mono text-2xs uppercase tracking-label text-faint", className)} role="status">
      {children}
    </div>
  );
}
