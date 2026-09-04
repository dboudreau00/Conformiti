import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { RISK_RATING, TONE_RING, TONE_TEXT, toneVar } from "../../utils/tone.js";
import { EASE } from "../layout/PanelTransition.jsx";
import { Legend } from "../ui/Meter.jsx";
import { Label, Loading, Panel, PanelHeader } from "../ui/Panel.jsx";
import { isLive, ratingFor } from "./vocab.js";

const LIKELIHOOD = [1, 2, 3, 4, 5];
const IMPACT = [5, 4, 3, 2, 1];
// Cell wash per rating band — the same tone the rating Badge uses.
const CELL_ALPHA = { low: 0.08, moderate: 0.12, high: 0.16, critical: 0.22 };
const MAX_BUBBLES = 4;

/** Likelihood × impact matrix of the live register. Each live risk is a bubble
 * in its cell; activating one selects it in the register beside / below. */
export function RiskHeatmap({ risks, stats, loading, selectedId, onSelect }) {
  const live = risks.filter(isLive);
  const byRating = stats?.by_rating;
  const legend = byRating
    ? [
        { label: "Critical", value: byRating.critical ?? 0, tone: RISK_RATING.critical },
        { label: "High", value: byRating.high ?? 0, tone: RISK_RATING.high },
        { label: "Moderate", value: byRating.moderate ?? 0, tone: RISK_RATING.moderate },
        { label: "Low", value: byRating.low ?? 0, tone: RISK_RATING.low },
      ]
    : null;

  return (
    <Panel>
      <PanelHeader title="Likelihood × impact" meta={loading ? "Loading" : `${live.length} live`} />
      {loading ? (
        <Loading>Loading matrix…</Loading>
      ) : (
        <div className="flex flex-wrap gap-6 p-5">
          <div className="min-w-[260px] flex-1">
            <div className="flex gap-2">
              <div className="flex w-4 flex-col" aria-hidden="true">
                {IMPACT.map((i) => (
                  <span key={i} className="tabular flex min-h-[52px] flex-1 items-center justify-end font-mono text-2xs text-faint">
                    {i}
                  </span>
                ))}
              </div>
              <div className="grid flex-1 grid-cols-5 gap-1" role="group" aria-label="Live risks by likelihood and impact">
                {IMPACT.map((impact) =>
                  LIKELIHOOD.map((likelihood) => {
                    const band = ratingFor(likelihood * impact);
                    const tone = RISK_RATING[band];
                    const here = live.filter((r) => r.likelihood === likelihood && r.impact === impact);
                    const shown = here.slice(0, MAX_BUBBLES);
                    const extra = here.length - shown.length;
                    return (
                      <div
                        key={`${likelihood}-${impact}`}
                        className="flex min-h-[52px] flex-wrap items-center justify-center gap-0.5 rounded-md border border-line p-0.5"
                        style={{ backgroundColor: toneVar(tone, CELL_ALPHA[band]) }}
                        role="group"
                        aria-label={`Likelihood ${likelihood}, impact ${impact} (${band}): ${here.length} live risk${here.length === 1 ? "" : "s"}`}
                      >
                        {shown.map((r) => {
                          const rt = RISK_RATING[r.rating] || tone;
                          const active = selectedId === r.id;
                          return (
                            <motion.button
                              key={r.id}
                              type="button"
                              onClick={() => onSelect(r)}
                              title={r.title}
                              aria-label={`Select risk: ${r.title}`}
                              aria-pressed={active}
                              initial={{ scale: 0.6, opacity: 0 }}
                              animate={{ scale: 1, opacity: 1 }}
                              transition={{ duration: 0.24, ease: EASE }}
                              className={cn(
                                "tabular relative flex h-6 min-w-[26px] items-center justify-center rounded-full bg-surface px-1.5 font-mono text-2xs font-medium ring-1",
                                "transition-transform duration-150 ease-out hover:scale-105",
                                TONE_TEXT[rt],
                                TONE_RING[rt]
                              )}
                            >
                              {r.id}
                              {active ? (
                                <motion.span
                                  layoutId="risk-selected"
                                  className="absolute -inset-1 rounded-full ring-2 ring-accent"
                                  transition={{ type: "spring", stiffness: 520, damping: 36 }}
                                  aria-hidden="true"
                                />
                              ) : null}
                            </motion.button>
                          );
                        })}
                        {extra > 0 ? (
                          <span className="tabular px-1 font-mono text-2xs text-muted" title={`${extra} more in this cell`}>
                            +{extra}
                          </span>
                        ) : null}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
            <div className="mt-2 flex gap-1 pl-6" aria-hidden="true">
              {LIKELIHOOD.map((l) => (
                <span key={l} className="tabular flex-1 text-center font-mono text-2xs text-faint">
                  {l}
                </span>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <Label>Impact ↑ · Likelihood →</Label>
              <Label>Open &amp; mitigating only</Label>
            </div>
          </div>

          {legend ? (
            <div className="min-w-[220px] flex-1">
              <Label className="mb-2 block">Live by rating</Label>
              <Legend items={legend} columns={2} />
              <p className="mt-3 text-2xs leading-relaxed text-faint">
                Bubbles are risk ids. Closed and accepted risks are not plotted.
              </p>
            </div>
          ) : null}
        </div>
      )}
    </Panel>
  );
}
