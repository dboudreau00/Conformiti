import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { XIcon } from "lucide-react";
import { EASE } from "../layout/PanelTransition.jsx";
import { cn } from "../../utils/cn.js";
import { Button, IconButton } from "./Button.jsx";
import { Label } from "./Panel.jsx";

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
        let nodes = Array.from(frame.current.querySelectorAll(FOCUSABLE)).filter((n) => !n.disabled);
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
            "fixed inset-0 z-50 flex justify-center bg-ink/40 p-4",
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
      setError(err?.message || "That could not be saved.");
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
          onChange={(e) => setValue(e.target.value)}
        />
        <div className="mt-1 flex items-baseline justify-between gap-3">
          <span className="text-2xs text-faint">{hint}</span>
          {minLength > 0 ? (
            <Label className={cn("tabular", short ? "text-danger" : "text-faint")}>
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

export function ConfirmDialog({ open, title, description, confirmLabel = "Confirm", tone = "danger-solid", onConfirm, onClose, children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (open) { setBusy(false); setError(""); } }, [open]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      await onConfirm();
      onClose?.();
    } catch (err) {
      setError(err?.message || "That did not work.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} title={title} description={description} onClose={busy ? undefined : onClose} size="sm">
      {children}
      {error ? <p className="notice notice-err mt-3" role="alert">{error}</p> : null}
      <div className="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button type="button" variant={tone} size="sm" onClick={confirm} busy={busy}>
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}

/** `ask({ title, description, confirmLabel, tone, children, onConfirm })` opens it; render `confirmDialog`
 * somewhere. `onConfirm` may be async: the dialog stays open and busy until it settles. */
export function useConfirm() {
  const [request, setRequest] = useState(null);
  const confirmDialog = (
    <ConfirmDialog
      open={!!request}
      title={request?.title || ""}
      description={request?.description}
      confirmLabel={request?.confirmLabel || "Confirm"}
      tone={request?.tone}
      onClose={() => setRequest(null)}
      onConfirm={async () => { await request?.onConfirm?.(); }}
    >
      {request?.children}
    </ConfirmDialog>
  );
  return { ask: setRequest, confirmDialog };
}
