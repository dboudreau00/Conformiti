import { cn } from "../../utils/cn.js";
import { Button } from "./Button.jsx";

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
  // A string (or a number) is a caption and gets the Label treatment. Anything
  // else is markup the caller built, and wrapping it in a Label pushed its own
  // typography onto it: buttons in a letter-spaced monospace face and badges
  // shouting in capitals, which is how Pro's headers came to look nothing like
  // the core's.
  const caption = typeof meta === "string" || typeof meta === "number";
  return (
    <header className={cn("flex items-center justify-between gap-4 border-b border-line px-5 py-3.5", className)}>
      <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
      {meta === null || meta === undefined || meta === false || meta === ""
        ? null
        : caption ? <Label>{meta}</Label> : meta}
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
export function Empty({ title, children, action, className }) {
  return (
    <div className={cn("px-5 py-12 text-center", className)}>
      {title ? <p className="text-[13px] font-medium text-ink">{title}</p> : null}
      {children ? <p className="mt-1 text-xs text-muted">{children}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

/**
 * What a list shows when its request failed, which is not what it shows when
 * it is genuinely empty.
 *
 * "No frameworks available, seed a framework to populate the register" under a
 * red banner describes a state the workspace is not in, and sends the reader
 * to fix something that is not broken. This says the load failed and offers
 * the only useful action.
 */
export function LoadError({ what = "This", onRetry, className }) {
  return (
    <Empty
      title={`${what} could not be loaded`}
      className={className}
      action={onRetry ? <Button size="sm" variant="secondary" onClick={onRetry}>Try again</Button> : null}
    >
      The request did not come back. Nothing has changed, so trying again is safe.
    </Empty>
  );
}

export function Loading({ children = "Loading…", className }) {
  return (
    <div className={cn("px-5 py-10 text-center font-mono text-2xs uppercase tracking-label text-faint", className)} role="status">
      {children}
    </div>
  );
}
