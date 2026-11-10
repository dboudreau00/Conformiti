import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { XIcon } from "lucide-react";
import { EASE } from "../layout/PanelTransition.jsx";
import { errorText } from "../../utils/a11y.js";
import { cn } from "../../utils/cn.js";
import { Button, IconButton } from "./Button.jsx";
import { Label } from "./Panel.jsx";

/** What a failed submit or confirm shows. A caller's own `throw new Error("a sentence")` is shown as written;
 * anything that came off the network is read through errorText, so no status line, HTML page or "Network Error"
 * reaches the screen. */
function failText(err, fallback) {
  if (err?.response || err?.isAxiosError) return errorText(err, fallback);
  return err?.message || fallback;
}

const INITIAL_FOCUS = 'input, textarea, select, button:not([data-dialog-close]), [href], [tabindex]:not([tabindex="-1"])';
const FOCUSABLE = 'input, textarea, select, button, [href], [tabindex]:not([tabindex="-1"])';

function firstField(root) {
  return Array.from(root.querySelectorAll(INITIAL_FOCUS)).find((n) => !n.disabled) || null;
}

export function Dialog({
  open, title, description, onClose, children, size = "md", className, closeOnOverlay = true, placement = "center",
}) {
  const titleId = useId();
  const descId = useId();
  const frame = useRef(null);
  const restoreTo = useRef(null);
  // Read through a ref: as an effect dependency a fresh onClose each render would rebuild the focus
  // trap and send focus back to the first control.
  const closeRef = useRef(onClose);
  useLayoutEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return undefined;
    restoreTo.current = document.activeElement;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Late-loading content is watched for its first field; focus moves only if the frame still has it.
    let watch = null;
    const t = setTimeout(() => {
      const node = frame.current;
      if (!node) return;
      const first = firstField(node);
      if (first) { first.focus(); return; }
      node.focus();
      watch = new MutationObserver((_, observer) => {
        const field = firstField(node);
        if (!field) return;
        observer.disconnect();
        watch = null;
        if (document.activeElement === node) field.focus();
      });
      watch.observe(node, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });
    }, 0);
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current?.();
      } else if (e.key === "Tab" && frame.current) {
        // The page behind is not inert, so focus outside the dialog's controls is pulled back in.
        // tabIndex -1 (the unselected buttons of a roving group) is not a Tab stop, so it cannot be the first or last one.
        let nodes = Array.from(frame.current.querySelectorAll(FOCUSABLE)).filter((n) => !n.disabled && n.tabIndex >= 0);
        if (!nodes.length) nodes = [frame.current];
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        const current = document.activeElement;
        const within = nodes.includes(current);
        if (e.shiftKey && (current === first || !within)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (current === last || !within)) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      watch?.disconnect();
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      restoreTo.current?.focus?.();
    };
  }, [open]);

  const width = { sm: "max-w-[420px]", md: "max-w-[560px]", lg: "max-w-[760px]" }[size] || "max-w-[560px]";

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className={cn(
            "fixed inset-0 z-50 flex justify-center bg-scrim/60 p-4 backdrop-blur-sm",
            placement === "top" ? "items-start overflow-y-auto pt-[10vh]" : "items-center"
          )}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15, ease: EASE }}
          // preventDefault: a backdrop press must not take focus from the field, or from the control that
          // focus was handed back to on close.
          onMouseDown={(e) => {
            if (e.target !== e.currentTarget) return;
            e.preventDefault();
            if (closeOnOverlay) onClose?.();
          }}
        >
          <motion.div
            ref={frame}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descId : undefined}
            tabIndex={-1}
            className={cn("w-full rounded-2xl border border-line bg-surface shadow-xl outline-none", width, className)}
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.18, ease: EASE }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
              <div className="min-w-0">
                <h2 id={titleId} className="text-[15px] font-semibold text-ink">{title}</h2>
                {description ? <p id={descId} className="mt-1 text-[13px] leading-snug text-muted">{description}</p> : null}
              </div>
              <IconButton label="Close" data-dialog-close onClick={onClose}>
                <XIcon className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
              </IconButton>
            </div>
            <div className="px-5 py-4">{children}</div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

/** `onSubmit(value)` may be async: the dialog stays open and disabled until it settles, and closes only on success. */
export function TextDialog({
  open, title, description, label, initial = "", placeholder = "", multiline = false,
  minLength = 0, maxLength = 2000, required = true, submitLabel = "Save", tone = "primary",
  hint, onSubmit, onClose, closeOnOverlay = false,
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fieldId = useId();
  const hintId = useId();
  const countId = useId();

  useEffect(() => {
    if (open) { setValue(initial); setError(""); setBusy(false); }
  }, [open, initial]);

  const trimmed = value.trim();
  const short = minLength > 0 && trimmed.length < minLength;
  const invalid = (required && !trimmed) || short;

  async function submit(e) {
    e.preventDefault();
    if (invalid || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit(trimmed);
      onClose?.();
    } catch (err) {
      setError(failText(err, "That could not be saved."));
    } finally {
      setBusy(false);
    }
  }

  const Field = multiline ? "textarea" : "input";
  return (
    <Dialog open={open} title={title} description={description} onClose={busy ? undefined : onClose} closeOnOverlay={closeOnOverlay}>
      <form onSubmit={submit} noValidate>
        <label htmlFor={fieldId} className="field-label">{label}</label>
        <Field
          id={fieldId}
          className={cn("input", multiline && "min-h-[120px] resize-y")}
          rows={multiline ? 5 : undefined}
          value={value}
          placeholder={placeholder}
          maxLength={maxLength}
          disabled={busy}
          aria-required={required || undefined}
          aria-describedby={[hint ? hintId : "", minLength > 0 ? countId : ""].filter(Boolean).join(" ") || undefined}
          onChange={(e) => setValue(e.target.value)}
        />
        <div className="mt-1 flex items-baseline justify-between gap-3">
          <span id={hintId} className="text-2xs text-faint">{hint}</span>
          {minLength > 0 ? (
            <Label id={countId} className={cn("tabular", short ? "text-danger" : "text-faint")}>
              {trimmed.length}/{minLength} minimum
            </Label>
          ) : null}
        </div>
        {error ? <p className="notice notice-err mt-3" role="alert">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant={tone} size="sm" busy={busy} disabled={invalid}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// A confirm button is primary when its label opens with one of these plain, constructive verbs. Anything else
// (Delete, Remove, Revoke, Reset, Discard, Leave without saving, a label nobody has classified) is treated as
// destructive and stays solid danger: an unclassified act warns rather than passes. A caller's `tone` always wins.
const CONSTRUCTIVE = /^(send|save|import|export|submit|mark|complete|add|create|file|raise|run|record|reopen|install|schedule|approve|accept|continue|apply|publish|start|turn on|switch on|enable|download|open)\b/i;

/** `confirmLabel` is required and names the act: the verb and the thing ("Delete folder", "Remove vendor"), never a bare
 * "Confirm". `tone` is optional: without it the button is primary for a constructive verb and solid danger for
 * everything else, so a caller that forgets it cannot make a destructive act look safe. */
export function ConfirmDialog({ open, title, description, confirmLabel, cancelLabel = "Cancel", tone, onConfirm, onClose, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (open) { setBusy(false); setError(""); } }, [open]);
  useEffect(() => {
    if (open && !confirmLabel) console.error('ConfirmDialog needs a confirmLabel: the verb and the thing, such as "Delete folder".');
  }, [open, confirmLabel]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
      onClose?.();
    } catch (err) {
      setError(failText(err, "That did not work."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} title={title} description={description} onClose={busy ? undefined : onClose} size="sm">
      {children}
      {error ? <p className="notice notice-err mt-3" role="alert">{error}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>{cancelLabel}</Button>
        <Button
          type="button"
          variant={tone || (CONSTRUCTIVE.test(confirmLabel || "") ? "primary" : "danger-solid")}
          size="sm"
          onClick={confirm}
          busy={busy}
        >
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}

/** `ask({ title, description, confirmLabel, cancelLabel, tone, children, onConfirm })` opens it; render `confirmDialog`
 * somewhere. `confirmLabel` and `tone` are ConfirmDialog's. `onConfirm` may be async: the dialog stays open and
 * busy until it settles. */
export function useConfirm() {
  const [request, setRequest] = useState(null);
  const confirmDialog = (
    <ConfirmDialog
      open={!!request}
      title={request?.title || ""}
      description={request?.description}
      confirmLabel={request?.confirmLabel}
      cancelLabel={request?.cancelLabel || undefined}
      tone={request?.tone}
      onClose={() => setRequest(null)}
      onConfirm={async () => { await request?.onConfirm?.(); }}
    >
      {request?.children}
    </ConfirmDialog>
  );
  return { ask: setRequest, confirmDialog };
}
