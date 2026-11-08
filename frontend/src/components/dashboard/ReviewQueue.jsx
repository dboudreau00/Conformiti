import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckIcon } from "lucide-react";
import api from "../../api/client.js";
import { useShell } from "../../shell.js";
import { errorText } from "../../utils/a11y.js";
import { dueTone, dueWords } from "../../utils/tone.js";
import { EASE } from "../layout/PanelTransition.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { useConfirm } from "../ui/Dialog.jsx";
import { Empty, Label, Panel, PanelHeader } from "../ui/Panel.jsx";

const PAGE = 8;
// Mirrors REVIEWS_CAP in backend/documents/views.py: a full list means more are due than the queue shows.
const REVIEWS_CAP = 500;

/** What `useConfirm().ask` takes to mark one document reviewed; the calendar asks the same question. */
export function reviewRequest(name, onConfirm) {
  return {
    title: `Mark ${name} reviewed?`,
    description: "Today becomes the review date and the document is set to Approved. This is written to the audit trail.",
    confirmLabel: "Mark reviewed",
    tone: "primary",
    onConfirm,
  };
}

/** `reviews`: rows of GET /documents/reviews/?days=120. The API refuses Mark reviewed without edit access to the
 * folder, so it is offered only to those who can manage documents or folders, and a refusal is shown. */
export function ReviewQueue({ me, reviews = [], onChanged }) {
  const { refreshCounts } = useShell();
  const { ask, confirmDialog } = useConfirm();
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState(0);
  const [showAll, setShowAll] = useState(false);

  const canReview = !!(me?.capabilities?.manage_documents || me?.capabilities?.manage_folders);
  const sorted = [...reviews].sort((a, b) => (a.days_until_review ?? Infinity) - (b.days_until_review ?? Infinity));
  const visible = showAll ? sorted : sorted.slice(0, PAGE);
  const hidden = sorted.length - visible.length;

  async function markReviewed(doc) {
    setError("");
    setBusyId(doc.id);
    try {
      await api.post(`/documents/${doc.id}/mark_reviewed/`);
      setReviewed((n) => n + 1);
      await onChanged?.();
      refreshCounts();
    } catch (e) {
      setError(errorText(e, `"${doc.name}" could not be marked reviewed. Try again.`));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Panel className="flex h-full flex-col overflow-hidden">
      <PanelHeader inline title="Reviews coming up" meta="Next 120 days">
        <Label className="tabular">{sorted.length}{sorted.length >= REVIEWS_CAP ? "+" : ""} open</Label>
      </PanelHeader>

      {error ? (
        <div className="notice notice-err mx-4 mt-3" role="alert">
          {error}
        </div>
      ) : null}

      <ul className="flex-1 divide-y divide-line">
        <AnimatePresence initial={false}>
          {visible.map((r) => (
            <motion.li
              key={r.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: 24, height: 0 }}
              transition={{ duration: 0.22, ease: EASE }}
              className="flex items-center gap-3 px-4 py-2.5"
            >
              <Badge tone={dueTone(r.days_until_review)} dot className="tabular min-w-[112px] shrink-0 justify-center">
                {dueWords(r.days_until_review)}
              </Badge>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium leading-tight text-ink">{r.name}</p>
                <p className="truncate font-mono text-2xs uppercase tracking-label text-faint">
                  {r.folder_path || "-"}
                  {r.owner_name ? ` / ${r.owner_name}` : ""}
                </p>
              </div>
              {canReview ? (
                <Button
                  size="sm"
                  className="shrink-0"
                  disabled={busyId != null}
                  aria-label={`Mark reviewed: ${r.name}`}
                  onClick={() => ask(reviewRequest(r.name, () => markReviewed(r)))}
                  icon={<CheckIcon className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" />}
                >
                  {busyId === r.id ? "Marking…" : "Mark reviewed"}
                </Button>
              ) : null}
            </motion.li>
          ))}
        </AnimatePresence>
        {sorted.length === 0 ? (
          <motion.li
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.24, ease: EASE }}
            className="flex flex-col items-center pt-8"
          >
            <CheckIcon className="h-5 w-5 text-success" strokeWidth={2} aria-hidden="true" />
            <Empty className="py-3" title="Nothing left to review" />
          </motion.li>
        ) : null}
      </ul>

      {hidden > 0 || showAll ? (
        <div className="border-t border-line px-4 py-2.5">
          <button type="button" className="link" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show ${hidden} more`}
          </button>
        </div>
      ) : null}

      <AnimatePresence initial={false}>
        {reviewed > 0 ? (
          <motion.footer
            key="reviewed"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="overflow-hidden border-t border-line bg-surface-2"
          >
            <div className="flex items-center justify-between px-4 py-2.5">
              <Label className="text-muted">
                {reviewed} reviewed this session
              </Label>
            </div>
          </motion.footer>
        ) : null}
      </AnimatePresence>
      {confirmDialog}
    </Panel>
  );
}
