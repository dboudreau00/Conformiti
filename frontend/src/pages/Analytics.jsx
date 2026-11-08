import { useCallback, useEffect, useState } from "react";
import api from "../api/client.js";
import { BarChart } from "../components/charts/BarChart.jsx";
import { DonutLegend } from "../components/charts/Donut.jsx";
import DocumentViewer from "../components/documents/DocumentViewer.jsx";
import { PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Legend, Meter, SegmentBar } from "../components/ui/Meter.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { ShowMore } from "../components/ui/ShowMore.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { loadFailReason } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";
import { CONTROL_STATUS, DOC_STATUS, TONE_TEXT, dueWords, monthDelta } from "../utils/tone.js";

// Organisation-wide, except documents: the server already filters those to the folders the caller may see.
const SUMMARY_URL = "/analytics/summary/";

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

function DonutPanel({ title, meta, slices, centerValue, centerLabel, emptyTitle }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader title={title} meta={meta} />
      {total > 0 ? (
        <div className="flex flex-1 flex-col justify-center p-5">
          <DonutLegend slices={slices} centerValue={centerValue} centerLabel={centerLabel} />
        </div>
      ) : (
        <Empty title={emptyTitle} />
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
  const [viewing, setViewing] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.get(SUMMARY_URL);
      setData(r.data);
    } catch (e) {
      setError(loadFailReason(e));
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
        <Loading>Loading analytics…</Loading>
      </PanelTransition>
    );
  }

  if (error || !data) {
    return (
      <PanelTransition>
        <Panel>
          <LoadError what="Analytics" reason={error} onRetry={load} />
        </Panel>
      </PanelTransition>
    );
  }

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

  // Worst first. A framework with nothing applicable has no readiness (the API's pct of 0 there means nothing to
  // measure), so it sorts last instead of topping the list.
  const readinessOf = (f) => (f.applicable ? f.pct ?? pctOf(f.implemented, f.applicable) : null);
  const sortedFrameworks = [...frameworks].sort((a, b) => {
    const pa = readinessOf(a);
    const pb = readinessOf(b);
    return pa === null || pb === null ? (pa === null) - (pb === null) : pa - pb;
  });

  const controlSlices = slicesFrom(CONTROL_STATUS, cs);
  const docSlices = slicesFrom(DOC_STATUS, ds);
  const withEvidence = controls.with_evidence || 0;

  const bars = timeline.map((t) => ({ label: t.label, value: t.count || 0 }));
  const liveRisks = risks.total_live || 0;
  const overdueTotal = revs.overdue || 0;
  const deltaBadge = delta != null ? monthDelta(delta) : null;

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        <StackItem className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Share implemented" value={readinessPct} suffix="%">
            <Meter value={readinessPct} total={100} className="mt-3" delay={0.08} ariaLabel="Share implemented" />
            {deltaBadge ? <Badge tone={deltaBadge.tone} mono className="mt-2 self-start">{deltaBadge.text}</Badge> : null}
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
            detail={`${revs.due_30 || 0} due in 30 days · ${revs.scheduled || 0} scheduled`}
            tone={overdueTotal > 0 ? "danger" : undefined}
          />
        </StackItem>

        <StackItem>
          <Panel>
            <PanelHeader title="Implementation by framework" />
            {frameworks.length === 0 ? (
              <Empty title="No frameworks loaded" />
            ) : (
              <div className="p-5">
                <ShowMore total={sortedFrameworks.length} initial={8} noun="frameworks">
                  {(n) => (
                    <div className="space-y-5">
                      {sortedFrameworks.slice(0, n).map((f, i) => {
                        const pct = readinessOf(f);
                        return (
                          <div key={f.key || f.name}>
                            <div className="mb-2 flex items-baseline justify-between gap-3">
                              <h3 className="flex min-w-0 items-baseline gap-2 text-[13px] font-semibold text-ink">
                                <span className="truncate">{f.name}</span>
                                {f.version ? <Label>{f.version}</Label> : null}
                              </h3>
                              <span className="tabular shrink-0 font-mono text-2xs uppercase tracking-label text-muted">
                                {pct === null ? "None applicable" : `${pct}% · ${f.implemented}/${f.applicable}`}
                              </span>
                            </div>
                            <SegmentBar
                              total={f.total}
                              delay={i * 0.06}
                              segments={slicesFrom(CONTROL_STATUS, f.by_status)}
                              ariaLabel={
                                pct === null
                                  ? `${f.name}: no applicable controls`
                                  : `${f.name}: ${pct}% of applicable controls implemented`
                              }
                            />
                          </div>
                        );
                      })}
                    </div>
                  )}
                </ShowMore>
                <Legend items={controlSlices} className="mt-5 border-t border-line pt-4 sm:grid-cols-4" />
              </div>
            )}
          </Panel>
        </StackItem>

        <StackItem className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <DonutPanel
            title="Control status"
            meta={`${withEvidence}/${controlTotal} have evidence`}
            slices={controlSlices}
            centerValue={String(controlTotal)}
            centerLabel="controls"
            emptyTitle="No controls yet"
          />
          <DonutPanel
            title="Document status"
            slices={docSlices}
            centerValue={String(docs.total || 0)}
            centerLabel="documents"
            emptyTitle="No documents visible"
          />
        </StackItem>

        <StackItem className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Panel className="flex h-full flex-col">
            <PanelHeader title="Review load" meta="Next 6 months" />
            {bars.length === 0 ? (
              <Empty title="No review timeline" />
            ) : (
              <div className="flex flex-1 flex-col p-5">
                <BarChart bars={bars} ariaLabel="Scheduled document reviews per month for the next six months" />
              </div>
            )}
          </Panel>

          <Panel className="flex h-full flex-col">
            <PanelHeader title="Ownership coverage" />
            <div className="space-y-4 p-5">
              <CoverageRow label="Controls with an owner" owned={controls.owned || 0} total={controlTotal} delay={0} />
              <CoverageRow label="Documents with an owner" owned={docs.owned || 0} total={docs.total || 0} delay={0.06} />
              <CoverageRow label="Risks with a treatment owner" owned={risks.owned || 0} total={liveRisks} delay={0.12} />
            </div>
          </Panel>
        </StackItem>

        <StackItem>
          <Panel className="overflow-hidden">
            <PanelHeader title="Most overdue documents" />
            {overdueSample.length === 0 ? (
              <Empty title="No overdue documents" />
            ) : (
              <ul className="divide-y divide-line">
                {overdueSample.map((d) => (
                  <li key={d.id} className="flex items-center gap-3 px-5 py-2.5">
                    <Badge tone="danger" dot className="tabular min-w-[112px] shrink-0 justify-center">
                      {dueWords(-d.days_overdue)}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        className="block min-w-0 max-w-full truncate text-left text-[13px] font-medium leading-tight text-ink hover:text-accent"
                        onClick={() =>
                          setViewing({
                            title: d.name,
                            previewUrl: `/documents/${d.id}/preview/`,
                            downloadUrl: `/documents/${d.id}/download/`,
                            filename: d.name,
                          })
                        }
                      >
                        {d.name}
                      </button>
                      <p className="truncate font-mono text-2xs uppercase tracking-label text-faint">{d.folder_path || "-"}</p>
                    </div>
                    <span className={cn("shrink-0 font-mono text-2xs", d.owner ? "text-muted" : "text-faint")}>
                      {d.owner || "No owner"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </StackItem>
      </Stack>

      <DocumentViewer open={!!viewing} {...(viewing || {})} onClose={() => setViewing(null)} />
    </PanelTransition>
  );
}
