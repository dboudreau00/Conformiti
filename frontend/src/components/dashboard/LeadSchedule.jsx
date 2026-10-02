import { Link } from "react-router-dom";
import { PaperclipIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";
import { Empty, Label, LoadError, Panel, PanelHeader } from "../ui/Panel.jsx";
import { ShowMore } from "../ui/ShowMore.jsx";
import { StatusGlyph } from "./StatusGlyph.jsx";

/** Rows drawn before "Show all": the schedule sits beside the readiness card,
 * and twenty-five frameworks would run it several screens past it. */
const ROWS = 6;

const num = (v) => (v === null || v === undefined ? "-" : Number(v).toLocaleString());

function Head({ glyph, children, first }) {
  return (
    <th scope="col" className={cn("px-[var(--sc-pad)] pb-2 pt-3 align-bottom font-normal", first ? "pl-5 text-left" : "text-right last:pr-5")}>
      <span className={cn("flex flex-col gap-1.5", first ? "items-start" : "items-end")}>
        <span className="flex h-3.5 items-center text-muted">{glyph}</span>
        {/* Two short lines beat a wide one: six numeric columns have to share
         * what the framework names leave of a narrow page. */}
        <Label className="whitespace-normal text-[10px] leading-[13px] tracking-[0.05em]">{children}</Label>
      </span>
    </th>
  );
}

function Sub({ total, notApplicable }) {
  return (
    <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs leading-4 text-muted">
      <span>
        {total.toLocaleString()} controls{notApplicable > 0 ? "," : ""}
      </span>
      {notApplicable > 0 ? (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <StatusGlyph status="not_applicable" size={10} />
          {notApplicable.toLocaleString()} not applicable
        </span>
      ) : null}
    </span>
  );
}

const CELL = "tabular px-[var(--sc-pad)] text-right font-mono text-[13px] text-ink last:pr-5";

/** One row per framework, footed. Applicable is everything not marked not
 * applicable, so it is also implemented plus in progress plus not started.
 * Readiness is the mean control score (what the headline is, framework by
 * framework), which is not the share implemented: the two answer different
 * questions and the register uses the first. The total row quotes the
 * programme's own figures rather than adding the rounded rows up. */
export function LeadSchedule({ frameworks, readiness, controls, onRetry }) {
  const known = Array.isArray(frameworks) && readiness && controls;
  const rows = known ? frameworks : [];

  return (
    <Panel className="sched-panel flex h-full min-w-0 flex-col">
      <PanelHeader title="Lead schedule" meta={known ? `${rows.length} ${rows.length === 1 ? "framework" : "frameworks"}` : null} />
      {!known ? (
        <LoadError what="The lead schedule" onRetry={onRetry} />
      ) : rows.length === 0 ? (
        <Empty title="No frameworks yet">Frameworks and their controls appear here once a control library is loaded.</Empty>
      ) : (
        <ShowMore total={rows.length} initial={ROWS} noun="frameworks" className="flex flex-1 flex-col" buttonClassName="mx-5 mb-3 self-start">
          {(n) => (
            <div className="sched min-w-0 flex-1 overflow-x-auto">
              <table className="h-full w-full min-w-[var(--sc-min)] table-fixed border-collapse">
                <caption className="sr-only">
                  Controls by framework and status, footed. Readiness is the mean score of a framework's applicable controls.
                </caption>
                <colgroup>
                  <col />
                  <col className="w-[var(--sc-1)]" />
                  <col className="w-[var(--sc-2)]" />
                  <col className="w-[var(--sc-3)]" />
                  <col className="w-[var(--sc-4)]" />
                  <col className="w-[var(--sc-5)]" />
                  <col className="w-[var(--sc-6)]" />
                </colgroup>
                <thead>
                  <tr>
                    <Head first>Framework</Head>
                    <Head>Applicable</Head>
                    <Head glyph={<StatusGlyph status="implemented" />}>Implemented</Head>
                    <Head glyph={<StatusGlyph status="in_progress" />}>In progress</Head>
                    <Head glyph={<StatusGlyph status="not_started" />}>Not started</Head>
                    <Head glyph={<PaperclipIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>Evidence linked</Head>
                    <Head>Readiness</Head>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, n).map((f) => (
                    <tr key={f.id ?? f.key} className="transition-colors duration-150 ease-out hover:bg-ink/[0.025]">
                      <th scope="row" className="h-[46px] border-t border-line py-1 pl-5 pr-3 text-left font-normal">
                        <Link
                          to={`/controls?framework=${encodeURIComponent(f.key)}`}
                          className="block break-words text-[13px] font-semibold leading-[18px] tracking-[-0.005em] text-ink underline-offset-[3px] hover:underline"
                        >
                          {f.name}
                          {f.version ? <span className="ml-1.5 font-mono text-2xs font-normal text-faint">{f.version}</span> : null}
                        </Link>
                        <Sub total={f.total} notApplicable={f.by_status?.not_applicable || 0} />
                      </th>
                      <td className={cn(CELL, "border-t border-line")}>{num(f.applicable)}</td>
                      <td className={cn(CELL, "border-t border-line")}>{num(f.by_status?.implemented)}</td>
                      <td className={cn(CELL, "border-t border-line")}>{num(f.by_status?.in_progress)}</td>
                      <td className={cn(CELL, "border-t border-line")}>{num(f.by_status?.not_started)}</td>
                      <td className={cn(CELL, "border-t border-line")}>{num(f.with_evidence)}</td>
                      <td className={cn(CELL, "border-t border-line")}>{num(f.score)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-surface-2/50 font-semibold">
                    <th scope="row" className="h-[46px] border-b-4 border-t border-double border-b-ink/70 border-t-ink/70 py-1 pl-5 pr-3 text-left font-normal">
                      <span className="block text-[13px] font-semibold leading-[18px] text-ink">Total</span>
                      <Sub total={controls.total} notApplicable={controls.by_status?.not_applicable || 0} />
                    </th>
                    <TotalCell>{num(readiness.applicable)}</TotalCell>
                    <TotalCell>{num(controls.by_status?.implemented)}</TotalCell>
                    <TotalCell>{num(controls.by_status?.in_progress)}</TotalCell>
                    <TotalCell>{num(controls.by_status?.not_started)}</TotalCell>
                    <TotalCell>{num(controls.with_evidence)}</TotalCell>
                    <TotalCell>{num(readiness.score)}</TotalCell>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </ShowMore>
      )}
    </Panel>
  );
}

function TotalCell({ children }) {
  return (
    <td className={cn(CELL, "border-b-4 border-t border-double border-b-ink/70 border-t-ink/70 font-medium")}>{children}</td>
  );
}
