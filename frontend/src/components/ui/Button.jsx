import { forwardRef } from "react";
import { motion } from "framer-motion";
import { Loader2Icon } from "lucide-react";
import { cn } from "../../utils/cn.js";

const VARIANTS = {
  primary:
    "bg-accent text-accent-ink border border-accent/0 hover:brightness-110 active:brightness-95 shadow-[0_1px_2px_rgb(0_0_0/0.12)]",
  secondary: "bg-surface text-ink border border-line hover:border-line-strong hover:bg-surface-2",
  ghost: "bg-transparent text-muted border border-transparent hover:bg-surface-2 hover:text-ink",
  // The quiet one, for an inline button on a page.
  danger: "bg-danger/[0.12] text-danger border border-danger/25 hover:bg-danger/20",
  // The confirm of a dialog that cannot be undone: primary's weight in the
  // danger colour. Its ink is a token because white on the dark packs' danger
  // colours measures under 3:1.
  "danger-solid":
    "bg-danger text-danger-ink border border-danger/0 hover:brightness-110 active:brightness-95 shadow-[0_1px_2px_rgb(0_0_0/0.12)]",
};

const SIZES = {
  sm: "h-7 px-2.5 text-xs gap-1.5 rounded-md",
  md: "h-9 px-3.5 text-[13px] gap-2 rounded-lg",
};

/** The one button. `type` defaults to "button" so a stray click inside a form
 * never submits it, pass type="submit" explicitly for submit buttons.
 *
 * `busy` is for a button whose action is in flight: it disables the button,
 * sets aria-busy and puts a spinner where the icon goes, and the label stays
 * as it is, so the name does not change and a longer or shorter word does not
 * move its neighbours. A button with an icon keeps its width exactly; one
 * without gains the spinner's width at its leading edge. */
export const Button = forwardRef(function Button(
  { variant = "secondary", size = "md", icon, busy = false, disabled, className, children, type = "button", ...rest },
  ref
) {
  return (
    <motion.button
      ref={ref}
      type={type}
      whileTap={{ scale: 0.975 }}
      transition={{ duration: 0.12, ease: [0.23, 1, 0.32, 1] }}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cn(
        "inline-flex items-center justify-center font-medium",
        "transition-[background-color,border-color,color,filter] duration-150 ease-out",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant] || VARIANTS.secondary,
        SIZES[size] || SIZES.md,
        className
      )}
      {...rest}
    >
      {busy ? <Loader2Icon className="h-3.5 w-3.5 shrink-0 animate-spin" strokeWidth={2} aria-hidden="true" /> : icon}
      {children}
    </motion.button>
  );
});

/** Small icon-only square button (toolbar affordances). */
export function IconButton({ label, className, children, ...rest }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "flex h-7 w-7 items-center justify-center rounded-md border border-line text-muted",
        "transition-colors duration-150 ease-out hover:border-line-strong hover:text-ink disabled:opacity-50",
        className
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
