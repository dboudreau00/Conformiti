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
import { InfoTip } from "../components/ui/InfoTip.jsx";
import { Legend, SegmentBar } from "../components/ui/Meter.jsx";
import { Empty, Label, LoadError, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { joinAll } from "../components/ui/ShowMore.jsx";
import { loadFailReason } from "../utils/a11y.js";
import { CONTROL_STATUS } from "../utils/tone.js";

/** Everything the page loads up front. The summary already names every
 * framework, counts its controls and totals the documents, so neither the
 * framework list nor the document list is fetched for those. The
 * calendar fetches its own feed for the visible month, mark-reviewed lives in
 * the review queue, and the atlas is requested beside these rather than after
 * them: it is the largest response and must not hold the rest back. */
const SOURCES = [
  { key: "summary", label: "the analytics summary", url: "/analytics/summary/" },
  { key: "reviews", label: "upcoming reviews", url: "/documents/reviews/?days=120" },
];

const rows = (data) => (Array.isArray(data) ? data : data?.results || []);

function joinNames(names) {
  return joinAll(names);
}

/** Three frameworks read as a list; twenty-five read as a count. */
function frameworkPhrase(names) {
  return names.length > 3 ? `${names.length} frameworks` : joinAll(names);
}

export default function Dashboard({ me }) {
  // null until its request has succeeded once: a source that never arrived is
  // unknown, which is not the same as empty, and the figures built from it
  // show a dash rather than a zero.
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

  // Waits for `me`. The dashboard reads the whole programme, which an external
  // auditor may not: the shell sends them to /packages instead, but only once
  // it knows who they are. Firing on mount would put two 403s on their console
  // at every sign-in and load a screen they cannot fill.
  useEffect(() => {
    if (!me) return;
    load();
  }, [load, me]);

  // The atlas has its own request and its own failure: a refusal or a slow
  // answer leaves the rest of the dashboard standing, and a late answer to an
  // attempt that has since been replaced is dropped.
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

  // Display names only. A number is bound to the word before it with a
  // non-breaking space, so a narrow card never ends a line on "SOC" and starts
  // the next with "2" (or splits "ISO/IEC 27001" the same way).
  const fwNames = (summary?.frameworks || []).map((f) => (f.name || "").replace(/ (?=\d)/g, " "));

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

  const controlTotal = controls?.total || 0;

  if (loading) {
    return (
      <PanelTransition>
        <Loading>Loading dashboard…</Loading>
      </PanelTransition>
    );
  }

  // A phone has no room for the readiness tip's box, which hangs past the
  // card's right edge even while it is closed: clipped, not scrolled to.
  return (
    <PanelTransition className="max-md:overflow-x-clip">
      <Stack className="dash grid grid-cols-12 gap-4">
        {failed.length ? (
          <StackItem className="col-span-12">
            <div className="notice notice-warn flex flex-wrap items-center justify-between gap-3" role="status">
              <span>Couldn't load {joinNames(failed)}. Showing what is available.</span>
              <Button size="sm" onClick={load}>Retry</Button>
            </div>
          </StackItem>
        ) : null}

        {/* Row A: the one number the workspace is judged on, beside the schedule that foots to it */}
        <StackItem className="col-span-12">
          <div className="dash-lead">
            <Panel className="dash-ready flex h-full min-w-0 flex-col justify-between p-5">
              {readiness ? (
                <>
                  <div>
                    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
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

                  <div className="mt-4">
                    {trendPoints.length >= 2 ? (
                      <TrendLine points={trendPoints} height={72} ariaLabel={`Readiness trend over the last ${trendPoints.length} months`} />
                    ) : (
                      <div className="flex h-[72px] items-center justify-center rounded-lg border border-dashed border-line">
                        <Label>History builds from daily snapshots</Label>
                      </div>
                    )}
                  </div>

                  <div className="mt-4">
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

            <LeadSchedule frameworks={summary?.frameworks} readiness={readiness} controls={controls} onRetry={load} />
          </div>
        </StackItem>

        {/* Row B: every control as a square, lit by what answers the same theme */}
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
          {/* Anchor for the "Open the review queue" link on the Reviews overdue
           * cell above: ReviewQueue itself is a shared component, so the id
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
