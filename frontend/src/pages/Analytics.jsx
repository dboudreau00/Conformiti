import { useCallback, useEffect, useState } from "react";
import api from "../api/client.js";
import { BarChart } from "../components/charts/BarChart.jsx";
import { DonutLegend } from "../components/charts/Donut.jsx";
import { PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Legend, Meter, SegmentBar } from "../components/ui/Meter.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";
import { CONTROL_STATUS, DOC_STATUS, TONE_TEXT } from "../utils/tone.js";

/** Everything on this page comes from one read-only call. Control, framework
 * and risk figures are organisation-wide; document figures are already
 * filtered server-side to the folders the caller may see. There are no write
 * controls here, so no role gates apply — `me` is accepted for route parity. */
const SUMMARY_URL = "/analytics/summary/";

/** [{label, value, tone}] rows from a vocab map (tone.js) and a by_status block. */
function slicesFrom(vocab, byStatus) {
  return Object.entries(vocab).map(([key, meta]) => ({
    label: meta.label,
    value: byStatus?.[key] || 0,
    tone: meta.tone,
  }));
}

function pctOf(part, whole) {
  return whole ? Math.round((part / whole) * 100) : 0;
}

function coverageTone(pct) {
  if (pct == null) return "muted";
  if (pct >= 100) return "success";
  if (pct >= 60) return "warning";
  return "danger";
}

function DonutPanel({ title, meta, slices, centerValue, centerLabel, emptyTitle, children }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader title={title} meta={meta} />
      {total > 0 ? (
        <div className="flex flex-1 flex-col justify-center p-5">
          <DonutLegend slices={slices} centerValue={centerValue} centerLabel={centerLabel} />
        </div>
      ) : (
        <Empty title={emptyTitle}>{children}</Empty>
      )}
    </Panel>
  );
}

function CoverageRow({ label, owned, total, delay }) {
  const pct = total ? pctOf(owned, total) : null;
  const tone = coverageTone(pct);
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-[13px] text-ink">{label}</span>
        <span className={cn("tabular shrink-0 font-mono text-2xs", TONE_TEXT[tone])}>
          {pct == null ? "none tracked" : `${owned}/${total} · ${pct}%`}
        </span>
      </div>
      <Meter value={owned} total={total} tone={tone} delay={delay} ariaLabel={label} />
    </div>
  );
}

export default function Analytics({ me }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.get(SUMMARY_URL);
      setData(r.data);
    } catch (e) {
      setError(errorText(e, "Couldn't load analytics. Please try again."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <PanelTransition>
        <Loading>Crunching analytics…</Loading>
      </PanelTransition>
    );
  }

  if (error || !data) {
    return (
      <PanelTransition>
        <Panel className="p-5">
          <div className="notice notice-err" role="alert">
            {error || "Couldn't load analytics."}
          </div>
          <Button className="mt-4" onClick={load} disabled={loading}>
            Try again
          </Button>
        </Panel>
      </PanelTransition>
    );
  }

  // --- Derive every figure from the response; nothing here is invented. -----
  const controls = data.controls || {};
  const cs = controls.by_status || {};
  const docs = data.documents || {};
  const ds = docs.by_status || {};
  const revs = data.reviews || {};
  const risks = data.risks || {};
  const readiness = data.readiness || {};
  const frameworks = data.frameworks || [];
  const timeline = data.review_timeline || [];
  const overdueSample = data.overdue_sample || [];

  const controlTotal = controls.total || 0;
  const applicable = controls.applicable ?? Math.max(0, controlTotal - (cs.not_applicable || 0));
  const implemented = readiness.implemented ?? cs.implemented ?? 0;
  const readinessPct = readiness.pct ?? pctOf(implemented, applicable);
  const delta = readiness.delta_pts;

  const controlSlices = slicesFrom(CONTROL_STATUS, cs);
  const docSlices = slicesFrom(DOC_STATUS, ds);
  const withEvidence = controls.with_evidence || 0;

  const bars = timeline.map((t) => ({ label: t.label, value: t.count || 0 }));
  const sixMonthTotal = timeline.reduce((s, t) => s + (t.count || 0), 0);
  const peak = timeline.reduce((best, t) => ((t.count || 0) > (best?.count || 0) ? t : best), null);
  const noSchedule = revs.no_schedule || 0;

  const unownedControls = controls.unowned ?? Math.max(0, controlTotal - (controls.owned || 0));
  const unownedDocs = docs.unowned ?? Math.max(0, (docs.total || 0) - (docs.owned || 0));
  const liveRisks = risks.total_live || 0;
  const unownedRisks = Math.max(0, liveRisks - (risks.owned || 0));
  const gaps = [];
  if (unownedControls) gaps.push(`${unownedControls} ${unownedControls === 1 ? "control has" : "controls have"} no named owner.`);
  if (unownedDocs) gaps.push(`${unownedDocs} ${unownedDocs === 1 ? "document is" : "documents are"} unowned.`);
  if (unownedRisks) gaps.push(`${unownedRisks} live ${unownedRisks === 1 ? "risk has" : "risks have"} no treatment owner.`);

  const overdueTotal = revs.overdue || 0;

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        {/* Headline numbers */}
        <StackItem className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Overall readiness" value={readinessPct} suffix="%" detail={`${implemented} implemented ÷ ${applicable} applicable`}>
            <Meter value={readinessPct} total={100} className="mt-3" delay={0.08} ariaLabel="Overall readiness" />
            {delta != null ? (
              <p className={cn("tabular mt-2 font-mono text-2xs", delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "text-faint")}>
                {delta > 0 ? `+${delta}` : delta} pts this month
              </p>
            ) : null}
          </StatCard>
          <StatCard
            label="Controls implemented"
            value={cs.implemented || 0}
            suffix={`/${applicable}`}
            detail={`${cs.not_applicable || 0} marked not applicable`}
          />
          <StatCard
            label="Documents approved"
            value={ds.approved || 0}
            suffix={`/${docs.total || 0}`}
            detail={`${ds.expired || 0} expired · ${ds.in_review || 0} in review`}
          />
          <StatCard
            label="Reviews overdue"
            value={overdueTotal}
            detail={`${revs.due_30 || 0} due in 30d · ${revs.scheduled || 0} scheduled`}
            tone={overdueTotal > 0 ? "danger" : undefined}
          />
        </StackItem>

        {/* Per-framework readiness */}
        <StackItem>
          <Panel>
            <PanelHeader title="Framework readiness" meta="Implemented ÷ applicable" />
            {frameworks.length === 0 ? (
              <Empty title="No frameworks loaded">Readiness per standard appears once a framework is imported.</Empty>
            ) : (
              <div className="space-y-5 p-5">
                {frameworks.map((f, i) => {
                  const pct = f.pct ?? pctOf(f.implemented, f.applicable);
                  return (
                    <div key={f.key || f.name}>
                      <div className="mb-2 flex items-baseline justify-between gap-3">
                        <h3 className="flex min-w-0 items-baseline gap-2 text-[13px] font-semibold text-ink">
                          <span className="truncate">{f.name}</span>
                          {f.version ? <Label>{f.version}</Label> : null}
                        </h3>
                        <span className="tabular shrink-0 font-mono text-2xs uppercase tracking-label text-muted">
                          {pct}% · {f.implemented}/{f.applicable}
                        </span>
                      </div>
                      <SegmentBar
                        total={f.total}
                        delay={i * 0.06}
                        segments={slicesFrom(CONTROL_STATUS, f.by_status)}
                        ariaLabel={`${f.name}: ${pct}% of applicable controls implemented`}
                      />
                    </div>
                  );
                })}
                <Legend items={controlSlices} className="border-t border-line pt-4 sm:grid-cols-4" />
              </div>
            )}
          </Panel>
        </StackItem>

        {/* Status breakdowns */}
        <StackItem className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <DonutPanel
            title="Control status"
            meta={`${withEvidence}/${controlTotal} have evidence`}
            slices={controlSlices}
            centerValue={String(controlTotal)}
            centerLabel="controls"
            emptyTitle="No controls yet"
          >
            Controls arrive with the first imported framework.
          </DonutPanel>
          <DonutPanel
            title="Document status"
            meta="Visible to you"
            slices={docSlices}
            centerValue={String(docs.total || 0)}
            centerLabel="documents"
            emptyTitle="No documents visible"
          >
            Nothing in the folders you can see has been uploaded yet.
          </DonutPanel>
        </StackItem>

        {/* Review load + ownership */}
        <StackItem className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Panel className="flex h-full flex-col">
            <PanelHeader title="Review load" meta="Next 6 months" />
            {bars.length === 0 ? (
              <Empty title="No review timeline">Schedule a document review to populate the next six months.</Empty>
            ) : (
              <div className="flex flex-1 flex-col p-5">
                <BarChart bars={bars} ariaLabel="Scheduled document reviews per month for the next six months" />
                <p className="mt-3 text-xs leading-snug text-muted">
                  {sixMonthTotal === 0
                    ? "No reviews fall due in the next six months."
                    : `${sixMonthTotal} ${sixMonthTotal === 1 ? "review falls" : "reviews fall"} due in the next six months; ${peak.month} is the heaviest with ${peak.count}.`}
                  {noSchedule ? ` ${noSchedule} ${noSchedule === 1 ? "document has" : "documents have"} no review date.` : ""}
                </p>
              </div>
            )}
          </Panel>

          <Panel className="flex h-full flex-col">
            <PanelHeader title="Ownership coverage" meta="Assigned owners" />
            <div className="space-y-4 p-5">
              <CoverageRow label="Controls with an owner" owned={controls.owned || 0} total={controlTotal} delay={0} />
              <CoverageRow label="Documents with an owner" owned={docs.owned || 0} total={docs.total || 0} delay={0.06} />
              <CoverageRow label="Risks with a treatment owner" owned={risks.owned || 0} total={liveRisks} delay={0.12} />
              <div className="rounded-lg border border-line bg-surface-2 p-3">
                <Label className="mb-1 block">Gap</Label>
                <p className="text-xs leading-snug text-muted">
                  {gaps.length ? gaps.join(" ") : "Every control, document and live risk has a named owner."}
                </p>
              </div>
            </div>
          </Panel>
        </StackItem>

        {/* Overdue sample */}
        <StackItem>
          <Panel className="overflow-hidden">
            <PanelHeader title="Most overdue documents" meta="Oldest review dates" />
            {overdueSample.length === 0 ? (
              <Empty title="No overdue documents">Every scheduled review is within its window.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {overdueSample.map((d) => (
                  <li key={d.id} className="flex items-center gap-3 px-5 py-2.5">
                    <Badge tone="danger" dot mono className="tabular w-[64px] shrink-0 justify-center">
                      {d.days_overdue}d
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium leading-tight text-ink">{d.name}</p>
                      <p className="truncate font-mono text-2xs uppercase tracking-label text-faint">{d.folder_path || "—"}</p>
                    </div>
                    <span className={cn("shrink-0 font-mono text-2xs", d.owner ? "text-muted" : "text-faint")}>{d.owner || "unassigned"}</span>
                  </li>
                ))}
              </ul>
            )}
            {overdueTotal > overdueSample.length ? (
              <div className="border-t border-line px-5 py-2.5">
                <Label className="tabular">
                  Showing {overdueSample.length} of {overdueTotal} overdue
                </Label>
              </div>
            ) : null}
          </Panel>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
