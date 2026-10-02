import { Link } from "react-router-dom";
import { ArrowUpRightIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";
import { TONE_TEXT } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { Meter } from "../ui/Meter.jsx";
import { Label, Panel, PanelHeader } from "../ui/Panel.jsx";

const BIG = "tabular text-[30px] font-semibold leading-none tracking-[-0.03em]";
const UNKNOWN = "Unavailable until the analytics summary loads.";

function Cell({ label, children }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 bg-surface p-4 sm:p-5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function ArrowLink({ to, href, children }) {
  const inner = (
    <>
      {children}
      <ArrowUpRightIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
    </>
  );
  return to ? (
    <Link to={to} className="link mt-auto self-start pt-2">{inner}</Link>
  ) : (
    <a href={href} className="link mt-auto self-start pt-2">{inner}</a>
  );
}

/** What wants somebody's attention this week, one cell each: overdue reviews,
 * open risk, how much of the register has evidence behind it, and the
 * documents those reviews are of. A figure whose source did not load shows a
 * dash, not a zero: unknown is not empty. */
export function NeedsAttention({ overdue, due30, risks, controls, docs, docTotal }) {
  const total = controls?.total || 0;
  const withEvidence = controls?.with_evidence || 0;
  const evidencePct = total ? Math.round((withEvidence / total) * 100) : 0;
  const by = docs?.by_status || {};

  return (
    <Panel className="min-w-0 overflow-hidden">
      <PanelHeader title="Needs attention" />
      <div className="dash-cells bg-line">
        <Cell label="Reviews overdue">
          <div className="flex items-baseline gap-2">
            <span className={cn(BIG, overdue > 0 ? TONE_TEXT.danger : "text-ink")}>{overdue ?? "-"}</span>
            <span className="text-xs text-muted">overdue</span>
          </div>
          <p className="text-xs leading-snug text-muted">
            {due30 != null ? `${due30} due in the next 30 days` : "Unavailable until upcoming reviews load"}
          </p>
          <ArrowLink href="#review-queue">Open the review queue</ArrowLink>
        </Cell>

        <Cell label="Risk posture">
          {risks ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className={cn(BIG, "text-ink")}>{risks.open || 0}</span>
                <span className="text-xs text-muted">open</span>
                {risks.overdue > 0 ? (
                  <Badge tone="danger" className="ml-auto">
                    {risks.overdue} overdue
                  </Badge>
                ) : null}
              </div>
              <p className="text-xs leading-snug text-muted">
                {risks.mitigating || 0} mitigating · {risks.accepted || 0} accepted
              </p>
              <ArrowLink to="/risks">Risk register</ArrowLink>
            </>
          ) : (
            <p className="text-xs text-muted">{UNKNOWN}</p>
          )}
        </Cell>

        <Cell label="Evidence coverage">
          {controls ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className={cn(BIG, "text-ink")}>{evidencePct}%</span>
                <span className="tabular text-xs text-muted">
                  {withEvidence}/{total} controls
                </span>
              </div>
              <Meter value={withEvidence} total={total} className="mt-1" delay={0.1} ariaLabel="Evidence coverage" />
              <p className="text-xs leading-snug text-muted">{controls.evidence_links || 0} links between controls and documents.</p>
            </>
          ) : (
            <p className="text-xs text-muted">{UNKNOWN}</p>
          )}
        </Cell>

        <Cell label="Documents">
          <div className="flex items-baseline gap-2">
            <span className={cn(BIG, "text-ink")}>{docTotal ?? "-"}</span>
            <span className="text-xs text-muted">on file</span>
          </div>
          <p className="text-xs leading-snug text-muted">
            {docs ? `${by.approved || 0} approved · ${by.in_review || 0} in review · ${by.expired || 0} expired` : "Policies, procedures and evidence"}
          </p>
          <ArrowLink to="/documents">Open folders</ArrowLink>
        </Cell>
      </div>
    </Panel>
  );
}
