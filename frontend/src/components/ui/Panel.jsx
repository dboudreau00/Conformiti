import { cn } from "../../utils/cn.js";
import { Button } from "./Button.jsx";

/** A panel the backlight shows through. `lit` is for the one panel on a screen that wins: light runs round its edge
 * (in the Conformiti packs; elsewhere it is a plain panel). A lit panel's `className` places the panel and
 * `bodyClassName` lays out what is inside it. */
export function Panel({ children, className, bodyClassName, padded = false, lit = false, as: Tag = "section", ...rest }) {
  if (lit) {
    return (
      <Tag className={cn("lit", className)} {...rest}>
        <div className="lit-halo" aria-hidden="true">
          <div className="lit-ring"><div className="lit-orbit" /></div>
        </div>
        <div className="lit-ring" data-ring="base" aria-hidden="true"><div className="lit-orbit" /></div>
        <div className={cn("lit-body", padded && "p-5", bodyClassName)}>{children}</div>
      </Tag>
    );
  }
  return (
    <Tag
      className={cn(
        "glass rounded-panel border border-line shadow-panel",
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

/** No `title` (the page heading already says it) leaves a row that holds only the actions. `inline` sets a caption `meta` beside the title (baseline-aligned) and leaves `children` at the right edge. */
export function PanelHeader({ title, meta, children, className, inline = false }) {
  const caption = typeof meta === "string" || typeof meta === "number";
  const metaNode = meta === null || meta === undefined || meta === false || meta === ""
    ? null
    : caption ? <Label className="font-normal">{meta}</Label> : meta;
  const heading = title ? <h2 className="text-[15px] font-bold tracking-[-0.005em] text-ink">{title}</h2> : null;
  return (
    <header className={cn("flex items-center gap-4 border-b border-line px-5 py-4", title ? "justify-between" : "justify-end", className)}>
      {inline ? (
        <div className="flex items-baseline gap-3">
          {heading}
          {metaNode}
        </div>
      ) : (
        <>
          {heading}
          {metaNode}
        </>
      )}
      {children}
    </header>
  );
}

export function Label({ children, className, as: Tag = "span", ...rest }) {
  return (
    <Tag className={cn("whitespace-nowrap text-xs font-semibold text-faint", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function Divider({ className }) {
  return <div className={cn("h-px w-full bg-line", className)} />;
}

export function Empty({ title, children, action, className }) {
  return (
    <div className={cn("px-5 py-12 text-center", className)}>
      {title ? <p className="text-[13px] font-medium text-ink">{title}</p> : null}
      {children ? <p className="mt-1 text-xs text-muted">{children}</p> : null}
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

/** Pass `reason` when the server answered: a refusal (400, 403) is not a lost request, and retrying repeats it. */
export function LoadError({ what = "This", reason, onRetry, className }) {
  return (
    <Empty
      title={`${what} could not be loaded`}
      className={className}
      action={onRetry ? <Button size="sm" variant="secondary" onClick={onRetry}>Try again</Button> : null}
    >
      {reason || "The request did not come back. Try again."}
    </Empty>
  );
}

export function Loading({ children = "Loading…", className }) {
  return (
    <div className={cn("px-5 py-10 text-center text-xs font-semibold text-faint", className)} role="status">
      {children}
    </div>
  );
}
