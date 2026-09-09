/**
 * Modal dialogs, so that nothing in the product asks a legal question
 * through window.prompt.
 *
 * A management assertion is the statement an auditor relies on; a withdrawal
 * reason is written into the record for good. Both were being collected in
 * a browser prompt: unstyled, unlabelled, invisible to screen readers as a
 * form, impossible to validate before the person commits, and dismissed by
 * one wrong keystroke. Three components replace every one of them:
 *
 *   <Dialog>        the frame — overlay, title, Escape, focus, scroll lock
 *   <TextDialog>    one labelled field (input or textarea) with a submit
 *   <ConfirmDialog> a question with a confirm and a cancel
 *
 * Playwright drives them as ordinary dialogs (`getByRole("dialog")`), which
 * is also how a screen reader reaches them.
 */
import { useEffect, useId, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { XIcon } from "lucide-react";
import { EASE } from "../layout/PanelTransition.jsx";
import { cn } from "../../utils/cn.js";
import { Button, IconButton } from "./Button.jsx";
import { Label } from "./Panel.jsx";

const FOCUSABLE = 'input, textarea, select, button:not([data-dialog-close]), [href], [tabindex]:not([tabindex="-1"])';

export function Dialog({ open, title, description, onClose, children, size = "md", className }) {
  const titleId = useId();
  const descId = useId();
  const frame = useRef(null);
  const restoreTo = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    restoreTo.current = document.activeElement;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Focus the first field, else the frame itself, once it is in the DOM.
    const t = setTimeout(() => {
      const first = frame.current?.querySelector(FOCUSABLE);
      (first || frame.current)?.focus();
    }, 0);
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
      } else if (e.key === "Tab" && frame.current) {
        // Keep Tab inside the dialog: the page behind it is inert for now.
        const nodes = Array.from(frame.current.querySelectorAll(FOCUSABLE)).filter((n) => !n.disabled);
        if (!nodes.length) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      restoreTo.current?.focus?.();
    };
  }, [open, onClose]);

  const width = { sm: "max-w-[420px]", md: "max-w-[560px]", lg: "max-w-[760px]" }[size] || "max-w-[560px]";

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15, ease: EASE }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
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

/**
 * One field, one decision. `onSubmit(value)` may return a promise; the
 * dialog stays open and disabled until it settles, and closes only on
 * success, so a failed request is not lost with its text.
 */
export function TextDialog({
  open, title, description, label, initial = "", placeholder = "", multiline = false,
  minLength = 0, maxLength = 2000, required = true, submitLabel = "Save", tone = "primary",
  hint, onSubmit, onClose,
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
    <Dialog open={open} title={title} description={description} onClose={busy ? undefined : onClose}>
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
          <Button type="submit" variant={tone} size="sm" disabled={invalid || busy}>
            {busy ? "Working…" : submitLabel}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function ConfirmDialog({ open, title, description, confirmLabel = "Confirm", tone = "danger", onConfirm, onClose, children }) {
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
        <Button type="button" variant={tone} size="sm" onClick={confirm} disabled={busy}>
          {busy ? "Working…" : confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}
