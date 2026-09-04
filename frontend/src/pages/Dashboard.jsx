import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRightIcon } from "lucide-react";
import api from "../api/client.js";
import { TrendLine } from "../components/charts/TrendLine.jsx";
import { ComplianceCalendar } from "../components/dashboard/ComplianceCalendar.jsx";
import { ReviewQueue } from "../components/dashboard/ReviewQueue.jsx";
import { PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Legend, Meter, SegmentBar } from "../components/ui/Meter.jsx";
import { Empty, Label, Loading, Panel } from "../components/ui/Panel.jsx";
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
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
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
  const [summary, setSummary] = useState(null);
  const [frameworks, setFrameworks] = useState([]);
  const [reviews, setReviews] = useState([]);
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

  useEffect(() => {
    load();
  }, [load]);

  const readiness = summary?.readiness;
  const controls = summary?.controls;
  const docs = summary?.documents;
  const revs = summary?.reviews;
  const risks = summary?.risks;

  const fwList = frameworks.length ? frameworks : summary?.frameworks || [];
  const fwNames = fwList.map((f) => f.name);

  const statusSegments = useMemo(() => {
    const by = controls?.by_status || {};
    return Object.entries(CONTROL_STATUS).map(([key, meta]) => ({ label: meta.label, value: by[key] || 0, tone: meta.tone }));
  }, [controls]);
  const trendPoints = useMemo(() => (readiness?.trend || []).map((p) => ({ label: p.label, value: p.pct })), [readiness]);
  const delta = readiness?.delta_pts;

  const overdue = revs?.overdue ?? reviews.filter((r) => r.days_until_review < 0).length;
  const due30 = revs?.due_30 ?? reviews.filter((r) => r.days_until_review >= 0 && r.days_until_review <= 30).length;
  const docTotal = docs?.total ?? docCount ?? 0;
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
            <div className="notice notice-warn" role="status">
              Couldn't load {joinNames(failed)} — showing what's available.
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
                    <Label>Overall readiness</Label>
                    {delta != null ? (
                      <Badge tone={delta > 0 ? "success" : delta < 0 ? "danger" : "muted"} mono>
                        {delta > 0 ? `+${delta} pts this month` : delta < 0 ? `${delta} pts this month` : "No change this month"}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="mt-3 flex items-end gap-2">
                    <span className="tabular text-[64px] font-semibold leading-[0.85] tracking-[-0.045em] text-ink">{readiness.pct}</span>
                    <span className="tabular pb-1 text-2xl font-medium text-faint">%</span>
                  </div>
                  <p className="mt-2 max-w-[34ch] text-[13px] leading-snug text-muted">
                    {readiness.implemented} of {readiness.applicable} applicable controls implemented
                    {fwNames.length ? ` across ${joinNames(fwNames)}` : ""}.
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
                  <SegmentBar segments={statusSegments} total={controlTotal} height={10} ariaLabel={`Control status distribution across ${controlTotal} controls`} />
                  <Legend items={statusSegments} className="mt-3" />
                </div>
              </>
            ) : (
              <Empty title="Readiness unavailable">The analytics summary could not be loaded.</Empty>
            )}
          </Panel>
        </StackItem>

        {/* Supporting metrics */}
        <StackItem className="col-span-12 xl:col-span-7">
          <div className="grid h-full grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Frameworks" value={fwList.length} detail={fwNames.length ? fwNames.join(" · ") : "No frameworks loaded"}>
              {fwList.length ? (
                <ul className="mt-3 space-y-1.5">
                  {fwList.map((f) => (
                    <li key={f.key || f.name} className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs text-muted">{f.name}</span>
                      <span className="tabular font-mono text-2xs text-faint">active</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </StatCard>

            <StatCard
              label="Documents"
              value={docTotal}
              detail={docs ? `${docBy.approved || 0} approved · ${docBy.in_review || 0} in review · ${docBy.expired || 0} expired` : "Policies, procedures and evidence"}
            >
              <ArrowLink to="/documents">Open folders</ArrowLink>
            </StatCard>

            <StatCard label="Reviews overdue" value={overdue} detail={`${due30} due in the next 30 days`} tone={overdue > 0 ? "danger" : undefined}>
              <ArrowLink to="/documents">Resolve now</ArrowLink>
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
                  <p className="mt-2 text-xs text-muted">{controls.evidence_links || 0} control–document links.</p>
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
          <ComplianceCalendar refreshKey={version} />
        </StackItem>

        <StackItem className="col-span-12 2xl:col-span-4">
          <ReviewQueue me={me} reviews={reviews} onChanged={load} />
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
