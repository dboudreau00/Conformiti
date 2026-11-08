import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../api/client.js";
import { TrendLine } from "../components/charts/TrendLine.jsx";
import { ComplianceCalendar } from "../components/dashboard/ComplianceCalendar.jsx";
import { CoverageAtlas } from "../components/dashboard/CoverageAtlas.jsx";
import { LeadSchedule } from "../components/dashboard/LeadSchedule.jsx";
import { NeedsAttention } from "../components/dashboard/NeedsAttention.jsx";
import { ReviewQueue } from "../components/dashboard/ReviewQueue.jsx";
import { PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Legend, SegmentBar } from "../components/ui/Meter.jsx";
import { Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { joinAll } from "../components/ui/ShowMore.jsx";
import { loadFailReason } from "../utils/a11y.js";
import { CONTROL_STATUS, monthDelta } from "../utils/tone.js";

const SOURCES = [
  { key: "summary", label: "dashboard figures", url: "/analytics/summary/" },
  { key: "reviews", label: "upcoming reviews", url: "/documents/reviews/?days=120" },
];

const rows = (data) => (Array.isArray(data) ? data : data?.results || []);

function failedSentence(names) {
  const text = joinAll(names);
  return `${text.charAt(0).toUpperCase()}${text.slice(1)} could not be loaded. Showing what is available.`;
}

export default function Dashboard({ me }) {
  // null until its request has succeeded once: an unknown source is not an empty one, so its figures show a dash.
  const [summary, setSummary] = useState(null);
  const [reviews, setReviews] = useState(null);
  const [failed, setFailed] = useState([]);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const [atlas, setAtlas] = useState({ data: null, error: null, loading: true });
  const [atlasTry, setAtlasTry] = useState(0);

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
    if (got.reviews !== undefined) setReviews(rows(got.reviews));
    setFailed(broken);
    setLoading(false);
    setVersion((v) => v + 1);
  }, []);

  // Waits for `me`: an external auditor may not read the whole program, and the shell only redirects them once it
  // knows who they are, so firing on mount would put 403s on their console at every sign-in.
  useEffect(() => {
    if (!me) return;
    load();
  }, [load, me]);

  useEffect(() => {
    if (!me) return undefined;
    let alive = true;
    setAtlas((a) => ({ ...a, error: null, loading: true }));
    api
      .get("/controls/atlas/")
      .then((r) => alive && setAtlas({ data: r.data, error: null, loading: false }))
      .catch((e) => alive && setAtlas((a) => ({ data: a.data, error: loadFailReason(e), loading: false })));
    return () => {
      alive = false;
    };
  }, [me, atlasTry]);

  const readiness = summary?.readiness;
  const controls = summary?.controls;
  const docs = summary?.documents;
  const revs = summary?.reviews;
  const risks = summary?.risks;

  const statusSegments = useMemo(() => {
    const by = controls?.by_status || {};
    return Object.entries(CONTROL_STATUS).map(([key, meta]) => ({ label: meta.label, value: by[key] || 0, tone: meta.tone }));
  }, [controls]);
  const scored = readiness?.score !== null && readiness?.score !== undefined;
  const hero = scored ? readiness.score : readiness?.pct;
  const trendPoints = useMemo(() => {
    const points = readiness?.trend || [];
    const withScore = points.filter((p) => p.score !== null && p.score !== undefined);
    return withScore.length >= 2
      ? withScore.map((p) => ({ label: p.label, value: p.score }))
      : points.map((p) => ({ label: p.label, value: p.pct }));
  }, [readiness]);
  const delta = scored ? readiness?.score_delta_pts : readiness?.delta_pts;
  const deltaBadge = delta != null ? monthDelta(delta) : null;
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

  const controlTotal = controls?.total || 0;

  if (loading) {
    return (
      <PanelTransition>
        <Loading>Loading dashboard…</Loading>
      </PanelTransition>
    );
  }

  // max-md:overflow-x-clip: on a phone nothing here may widen the page.
  return (
    <PanelTransition className="max-md:overflow-x-clip">
      <Stack className="dash grid grid-cols-12 gap-4">
        {failed.length ? (
          <StackItem className="col-span-12">
            <div className="notice notice-warn flex flex-wrap items-center justify-between gap-3" role="status">
              <span>{failedSentence(failed)}</span>
              <Button size="sm" onClick={load}>Try again</Button>
            </div>
          </StackItem>
        ) : null}

        <StackItem className="col-span-12">
          <div className="dash-lead">
            <Panel className="dash-ready flex h-full min-w-0 flex-col justify-between p-5">
              {readiness ? (
                <>
                  <div>
                    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
                      <Label>{scored ? "Readiness score" : "Share implemented"}</Label>
                      {deltaBadge ? <Badge tone={deltaBadge.tone} mono>{deltaBadge.text}</Badge> : null}
                    </div>
                    <div className="mt-3 flex items-end gap-2">
                      <span className="tabular text-[64px] font-semibold leading-[0.85] tracking-[-0.045em] text-ink">{hero}</span>
                      <span className="tabular pb-1 text-2xl font-medium text-faint">{scored ? "/100" : "%"}</span>
                    </div>
                  </div>

                  <div className="mt-4">
                    {trendPoints.length >= 2 ? (
                      <TrendLine
                        points={trendPoints}
                        height={72}
                        ariaLabel={`Readiness trend over the last ${trendPoints.length} months`}
                      />
                    ) : (
                      <div className="flex h-[72px] items-center justify-center rounded-lg border border-dashed border-line">
                        <Label>No history yet</Label>
                      </div>
                    )}
                  </div>

                  <div className="mt-4">
                    {scored ? (
                      <>
                        <SegmentBar
                          segments={bandSegments}
                          total={readiness.applicable}
                          height={10}
                          ariaLabel={`Readiness bands across ${readiness.applicable} applicable controls`}
                        />
                        <Legend items={bandSegments} className="mt-3" />
                      </>
                    ) : (
                      <>
                        <SegmentBar
                          segments={statusSegments}
                          total={controlTotal}
                          height={10}
                          ariaLabel={`Control status distribution across ${controlTotal} controls`}
                        />
                        <Legend items={statusSegments} className="mt-3" />
                      </>
                    )}
                  </div>
                </>
              ) : (
                <LoadError what="Readiness" onRetry={load} />
              )}
            </Panel>

            <LeadSchedule frameworks={summary?.frameworks} readiness={readiness} controls={controls} onRetry={load} />
          </div>
        </StackItem>

        <StackItem className="col-span-12">
          <CoverageAtlas
            data={atlas.data}
            loading={atlas.loading}
            error={atlas.error}
            onRetry={() => setAtlasTry((n) => n + 1)}
          />
        </StackItem>

        <StackItem className="col-span-12">
          <NeedsAttention
            overdue={overdue}
            due30={due30}
            risks={risks}
            controls={controls}
            docs={docs}
            docTotal={docs?.total}
          />
        </StackItem>

        <StackItem className="dash-span-8 col-span-12">
          <ComplianceCalendar refreshKey={version} me={me} onChanged={load} />
        </StackItem>

        <StackItem className="dash-span-4 col-span-12">
          {/* #review-queue is the target of NeedsAttention's "Open the review queue" link. The queue is not drawn until
              reviews have loaded: given nothing, it claims there is nothing left to review. */}
          <div id="review-queue" className="h-full">
            {reviews ? (
              <ReviewQueue me={me} reviews={reviews} onChanged={load} />
            ) : (
              <Panel className="flex h-full flex-col">
                <PanelHeader inline title="Reviews coming up" meta="Next 120 days" />
                <LoadError what="Upcoming reviews" onRetry={load} />
              </Panel>
            )}
          </div>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
