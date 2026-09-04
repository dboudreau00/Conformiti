import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckIcon } from "lucide-react";
import api from "../../api/client.js";
import { useShell } from "../../shell.js";
import { errorText } from "../../utils/a11y.js";
import { dueLabel, dueTone } from "../../utils/tone.js";
import { EASE } from "../layout/PanelTransition.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { Empty, Label, Panel } from "../ui/Panel.jsx";

const PAGE = 8;

/** Upcoming document reviews (rows from GET /documents/reviews/?days=120,
 * loaded by the dashboard). Marking one reviewed needs edit access to its
 * folder — the API returns 403 otherwise — so the action is only offered to
 * users who can manage documents or folders, and a refusal is surfaced. */
export function ReviewQueue({ me, reviews = [], onChanged }) {
  const { refreshCounts } = useShell();
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [attested, setAttested] = useState(0);
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
      setAttested((n) => n + 1);
      await onChanged?.();
      refreshCounts();
    } catch (e) {
      setError(errorText(e, `Couldn't mark "${doc.name}" reviewed. Please try again.`));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Panel className="flex h-full flex-col overflow-hidden">
      <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Reviews coming up</h2>
          <Label>Next 120 days</Label>
        </div>
        <Label className="tabular">{sorted.length} open</Label>
      </header>

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
              <Badge tone={dueTone(r.days_until_review)} dot mono className="tabular w-[76px] shrink-0 justify-center">
                {dueLabel(r.days_until_review)}
              </Badge>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium leading-tight text-ink">{r.name}</p>
                <p className="truncate font-mono text-2xs uppercase tracking-label text-faint">
                  {r.folder_path || "—"}
                  {r.owner_name ? ` / ${r.owner_name}` : ""}
                </p>
              </div>
              {canReview ? (
                <Button
                  size="sm"
                  className="shrink-0"
                  disabled={busyId != null}
                  aria-label={`Mark ${r.name} reviewed`}
                  onClick={() => markReviewed(r)}
                  icon={<CheckIcon className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" />}
                >
                  {busyId === r.id ? "Marking…" : "Mark reviewed"}
                </Button>
              ) : null}
            </motion.li>
          ))}
        </AnimatePresence>
        {sorted.length === 0 ? (
          <motion.li initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.24, ease: EASE }} className="flex flex-col items-center pt-8">
            <CheckIcon className="h-5 w-5 text-success" strokeWidth={2} aria-hidden="true" />
            <Empty className="py-3" title="Every scheduled review is attested">
              Nothing is due in the next 120 days.
            </Empty>
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
        {attested > 0 ? (
          <motion.footer
            key="attested"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="overflow-hidden border-t border-line bg-surface-2"
          >
            <div className="flex items-center justify-between px-4 py-2.5">
              <Label className="text-muted">
                {attested} attested this session
              </Label>
            </div>
          </motion.footer>
        ) : null}
      </AnimatePresence>
    </Panel>
  );
}
