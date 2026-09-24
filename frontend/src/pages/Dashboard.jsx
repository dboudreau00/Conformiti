import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRightIcon } from "lucide-react";
import api from "../api/client.js";
import { TrendLine } from "../components/charts/TrendLine.jsx";
import { ComplianceCalendar } from "../components/dashboard/ComplianceCalendar.jsx";
import { ReviewQueue } from "../components/dashboard/ReviewQueue.jsx";
import { PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { InfoTip } from "../components/ui/InfoTip.jsx";
import { Legend, Meter, SegmentBar } from "../components/ui/Meter.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { ShowMore, joinAll, joinSome } from "../components/ui/ShowMore.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { cn } from "../utils/cn.js";
import { CONTROL_STATUS } from "../utils/tone.js";

/** Everything the page loads up front. The calendar fetches its own feed for
 * the visible month; mark-reviewed lives in the review queue. */
const SOURCES = [
  { key: "summary", label: "the analytics summary", url: "/analytics/summary/" },
  { key: "frameworks", label: "frameworks", url: "/frameworks/" },
  { key: "reviews", label: "upcoming reviews", url: "/documents/reviews/?days=120" },
  { key: "documents", label: "the document count", url: "/documents/?page_size=1" },
];

const rows = (data) => (Array.isArray(data) ? data : data?.results || []);

function joinNames(names) {
  return joinAll(names);
}

/** Three frameworks read as a list; twenty-five read as a count. */
function frameworkPhrase(names) {
  return names.length > 3 ? `${names.length} frameworks` : joinAll(names);
}

function ArrowLink({ to, children, className }) {
  return (
    <Link to={to} className={cn("link mt-3", className)}>
      {children}
      <ArrowUpRightIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
    </Link>
  );
}

const BIG = "tabular text-[30px] font-semibold leading-none tracking-[-0.03em] text-ink";

export default function Dashboard({ me }) {
  // null until its request has succeeded once: a source that never arrived is
  // unknown, which is not the same as empty, and the figures built from it
  // show a dash rather than a zero.
  const [summary, setSummary] = useState(null);
  const [frameworks, setFrameworks] = useState(null);
  const [reviews, setReviews] = useState(null);
  const [docCount, setDocCount] = useState(null);
  const [failed, setFailed] = useState([]);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  // allSettled, not all: one failing panel must not blank the whole dashboard.
  const load = useCallback(async () => {
    const results = await Promise.allSettled(SOURCES.map((s) => api.get(s.url)));
    const got = {};
    const broken = [];
    results.forEach((r, i) => {
      if (r.status === "fulfilled") got[SOURCES[i].key] = r.value.data;
      else broken.push(SOURCES[i].label);
    });
    if (got.summary !== undefined) setSummary(got.summary);
    if (got.frameworks !== undefined) setFrameworks(rows(got.frameworks));
    if (got.reviews !== undefined) setReviews(rows(got.reviews));
    if (got.documents !== undefined) setDocCount(got.documents?.count ?? rows(got.documents).length);
    setFailed(broken);
    setLoading(false);
    setVersion((v) => v + 1);
  }, []);

  // Waits for `me`. The dashboard reads the whole programme, which an external
  // auditor may not: the shell sends them to /packages instead, but only once
  // it knows who they are. Firing on mount put two 403s on their console every
  // time they signed in -- and would have loaded a screen they cannot fill.
  useEffect(() => {
    if (!me) return;
    load();
  }, [load, me]);

  const readiness = summary?.readiness;
  const controls = summary?.controls;
  const docs = summary?.documents;
  const revs = summary?.reviews;
  const risks = summary?.risks;

  const fwList = frameworks?.length ? frameworks : summary?.frameworks || [];
  // Display names only. A number is bound to the word before it with a
  // non-breaking space, so a narrow card never ends a line on "SOC" and starts
  // the next with "2" (or splits "ISO/IEC 27001" the same way).
  const fwNames = fwList.map((f) => (f.name || "").replace(/ (?=\d)/g, "\u00a0"));
  const fwKnown = frameworks !== null || Array.isArray(summary?.frameworks);

  const statusSegments = useMemo(() => {
    const by = controls?.by_status || {};
    return Object.entries(CONTROL_STATUS).map(([key, meta]) => ({ label: meta.label, value: by[key] || 0, tone: meta.tone }));
  }, [controls]);
  // The headline is the register's score: implementation, an owner, evidence,
  // its freshness and a test, less open risks. The implemented share is shown
  // beside it. History recorded before 0.9.5 knew only the share, so the
  // trend line is the score once it exists and the share until then.
  const scored = readiness?.score !== null && readiness?.score !== undefined;
  const hero = scored ? readiness.score : readiness?.pct;
  const trendPoints = useMemo(() => {
    const points = readiness?.trend || [];
    const withScore = points.filter((p) => p.score !== null && p.score !== undefined);
    return withScore.length >= 2
      ? withScore.map((p) => ({ label: p.label, value: p.score }))
      : points.map((p) => ({ label: p.label, value: p.pct }));
  }, [readiness]);
  // The month-on-month badge sits beside the headline, so it must be the
  // headline's own delta: the score's once two scored snapshots exist (null
  // before that, so no badge), the share's when the share is the headline.
  const delta = scored ? readiness?.score_delta_pts : readiness?.delta_pts;
  const bandSegments = useMemo(() => {
    const by = readiness?.bands || {};
    return [
      { label: "Ready", value: by.ready || 0, tone: "success" },
      { label: "Nearly there", value: by.nearly || 0, tone: "warning" },
      { label: "At risk", value: by.at_risk || 0, tone: "danger" },
      { label: "Not ready", value: by.not_started || 0, tone: "faint" },
    ];
  }, [readiness]);

  const overdue = revs?.overdue ?? (reviews ? reviews.filter((r) => r.days_until_review < 0).length : null);
  const due30 = revs?.due_30 ?? (reviews ? reviews.filter((r) => r.days_until_review >= 0 && r.days_until_review <= 30).length : null);
  const docTotal = docs?.total ?? docCount;
  const docBy = docs?.by_status || {};

  const controlTotal = controls?.total || 0;
  const withEvidence = controls?.with_evidence || 0;
  const evidencePct = controlTotal ? Math.round((withEvidence / controlTotal) * 100) : 0;

  if (loading) {
    return (
      <PanelTransition>
        <Loading>Loading dashboard…</Loading>
      </PanelTransition>
    );
  }

  return (
    <PanelTransition>
      <Stack className="grid grid-cols-12 gap-4">
        {failed.length ? (
          <StackItem className="col-span-12">
            <div className="notice notice-warn flex flex-wrap items-center justify-between gap-3" role="status">
              <span>Couldn't load {joinNames(failed)}. Showing what is available.</span>
              <Button size="sm" onClick={load}>Retry</Button>
            </div>
          </StackItem>
        ) : null}

        {/* Hero: the one number the workspace is judged on */}
        <StackItem className="col-span-12 xl:col-span-5">
          <Panel className="flex h-full flex-col justify-between p-5">
            {readiness ? (
              <>
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <span className="flex items-center gap-1.5">
                      <Label>{scored ? "Readiness score" : "Overall readiness"}</Label>
                      <InfoTip label={scored ? "How the readiness score is worked out" : "How overall readiness is worked out"}>
                        {scored
                          ? `The mean score across ${readiness.applicable.toLocaleString()} applicable controls${fwNames.length ? ` in ${frameworkPhrase(fwNames)}` : ""}, the same score the register gives each control: implementation, an owner, evidence and its freshness, a test, less open risks.`
                          : `${readiness.implemented.toLocaleString()} of ${readiness.applicable.toLocaleString()} applicable controls${fwNames.length ? ` across ${frameworkPhrase(fwNames)}` : ""} are marked implemented.`}
                      </InfoTip>
                    </span>
                    {delta != null ? (
                      <Badge tone={delta > 0 ? "success" : delta < 0 ? "danger" : "muted"} mono>
                        {delta > 0 ? `+${delta} pts this month` : delta < 0 ? `${delta} pts this month` : "No change this month"}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="mt-3 flex items-end gap-2">
                    <span className="tabular text-[64px] font-semibold leading-[0.85] tracking-[-0.045em] text-ink">{hero}</span>
                    <span className="tabular pb-1 text-2xl font-medium text-faint">{scored ? "/100" : "%"}</span>
                  </div>
                  <p className="mt-2 max-w-[38ch] text-[13px] leading-snug text-muted">
                    {scored
                      ? `${readiness.pct}% of ${readiness.applicable.toLocaleString()} applicable controls are marked implemented.`
                      : `${readiness.implemented.toLocaleString()} of ${readiness.applicable.toLocaleString()} applicable controls implemented.`}
                  </p>
                </div>

                <div className="mt-5">
                  {trendPoints.length >= 2 ? (
                    <TrendLine points={trendPoints} ariaLabel={`Readiness trend over the last ${trendPoints.length} months`} />
                  ) : (
                    <div className="flex h-[96px] items-center justify-center rounded-lg border border-dashed border-line">
                      <Label>History builds from daily snapshots</Label>
                    </div>
                  )}
                </div>

                <div className="mt-5">
                  {scored ? (
                    <>
                      <SegmentBar segments={bandSegments} total={readiness.applicable} height={10} ariaLabel={`Readiness bands across ${readiness.applicable} applicable controls`} />
                      <Legend items={bandSegments} className="mt-3" />
                    </>
                  ) : (
                    <>
                      <SegmentBar segments={statusSegments} total={controlTotal} height={10} ariaLabel={`Control status distribution across ${controlTotal} controls`} />
                      <Legend items={statusSegments} className="mt-3" />
                    </>
                  )}
                </div>
              </>
            ) : (
              <Empty title="Readiness unavailable">
                The analytics summary could not be loaded.
                <Button size="sm" className="mt-3" onClick={load}>Try again</Button>
              </Empty>
            )}
          </Panel>
        </StackItem>

        {/* Supporting metrics */}
        <StackItem className="col-span-12 xl:col-span-7">
          <div className="grid h-full grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              label="Frameworks"
              value={fwKnown ? fwList.length : "-"}
              detail={fwNames.length ? joinSome(fwNames, 3) : fwKnown ? "No frameworks loaded" : "Unavailable until the framework list loads"}
            >
              {fwList.length ? (
                <ShowMore total={fwList.length} initial={8} noun="frameworks" className="mt-3">
                  {(n) => (
                    <ul className="space-y-1.5">
                      {fwList.slice(0, n).map((f) => (
                        <li key={f.key || f.name} className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs text-muted" title={f.name}>{f.name}</span>
                          <span className="tabular shrink-0 font-mono text-2xs text-faint">
                            {typeof f.control_count === "number" ? `${f.control_count} controls` : "active"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </ShowMore>
              ) : null}
            </StatCard>

            <StatCard
              label="Documents"
              value={docTotal ?? "-"}
              detail={docs ? `${docBy.approved || 0} approved · ${docBy.in_review || 0} in review · ${docBy.expired || 0} expired` : "Policies, procedures and evidence"}
            >
              <ArrowLink to="/documents">Open folders</ArrowLink>
            </StatCard>

            <StatCard
              label="Reviews overdue"
              value={overdue ?? "-"}
              detail={due30 != null ? `${due30} due in the next 30 days` : "Unavailable until upcoming reviews load"}
              tone={overdue > 0 ? "danger" : undefined}
            >
              <a href="#review-queue" className="link mt-3">
                Open the review queue
                <ArrowUpRightIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
              </a>
            </StatCard>

            <Panel className="p-4 sm:col-span-2">
              <Label>Evidence coverage</Label>
              {controls ? (
                <>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className={BIG}>{evidencePct}%</span>
                    <span className="tabular text-xs text-muted">
                      {withEvidence}/{controlTotal} controls
                    </span>
                  </div>
                  <Meter value={withEvidence} total={controlTotal} className="mt-3" delay={0.1} ariaLabel="Evidence coverage" />
                  <p className="mt-2 text-xs text-muted">{controls.evidence_links || 0} links between controls and documents.</p>
                </>
              ) : (
                <p className="mt-2 text-xs text-muted">Unavailable until the analytics summary loads.</p>
              )}
            </Panel>

            <Panel className="p-4">
              <Label>Risk posture</Label>
              {risks ? (
                <>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className={BIG}>{risks.open || 0}</span>
                    <span className="text-xs text-muted">open</span>
                    {risks.overdue > 0 ? (
                      <Badge tone="danger" className="ml-auto">
                        {risks.overdue} overdue
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-2 text-xs leading-snug text-muted">
                    {risks.mitigating || 0} mitigating · {risks.accepted || 0} accepted
                  </p>
                  <ArrowLink to="/risks">Risk register</ArrowLink>
                </>
              ) : (
                <p className="mt-2 text-xs text-muted">Unavailable until the analytics summary loads.</p>
              )}
            </Panel>
          </div>
        </StackItem>

        <StackItem className="col-span-12 2xl:col-span-8">
          <ComplianceCalendar refreshKey={version} me={me} onChanged={load} />
        </StackItem>

        <StackItem className="col-span-12 2xl:col-span-4">
          {/* Anchor for the "Open the review queue" link on the Reviews overdue
           * card above: ReviewQueue itself is a shared component, so the id
           * lives on this wrapper instead of inside it. Until the upcoming
           * reviews have loaded once, the queue is not drawn: given nothing, it
           * says every scheduled review is attested, and the link would land
           * the reader on that claim. */}
          <div id="review-queue" className="h-full">
            {reviews ? (
              <ReviewQueue me={me} reviews={reviews} onChanged={load} />
            ) : (
              <Panel className="flex h-full flex-col">
                <PanelHeader title="Reviews coming up" meta="Next 120 days" />
                <LoadError what="Upcoming reviews" onRetry={load} />
              </Panel>
            )}
          </div>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
