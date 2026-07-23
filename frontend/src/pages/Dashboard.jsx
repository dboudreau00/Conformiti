import { useEffect, useState } from "react";
import api from "../api/client.js";
import Calendar from "../components/Calendar.jsx";

function reviewBadge(days) {
  if (days < 0) return <span className="badge overdue"><span className="dot" />overdue</span>;
  if (days <= 14) return <span className="badge soon"><span className="dot" />{days}d</span>;
  return <span className="badge ok"><span className="dot" />{days}d</span>;
}

export default function Dashboard() {
  const [frameworks, setFrameworks] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [events, setEvents] = useState([]);
  const [docCount, setDocCount] = useState(0);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    const today = new Date();
    const start = new Date(today.getFullYear(), today.getMonth() - 1, 1).toISOString().slice(0, 10);
    const end = new Date(today.getFullYear(), today.getMonth() + 4, 0).toISOString().slice(0, 10);
    const [fw, rev, feed, docs, sum] = await Promise.all([
      api.get("/frameworks/"),
      api.get("/documents/reviews/?days=120"),
      api.get(`/calendar/feed/?start=${start}&end=${end}`),
      api.get("/documents/?page_size=1"),
      api.get("/analytics/summary/").catch(() => null),
    ]);
    setFrameworks(fw.data.results || fw.data);
    setReviews(rev.data);
    setEvents(feed.data);
    setDocCount(docs.data.count ?? (docs.data.results || docs.data).length);
    setSummary(sum?.data || null);
    setLoading(false);
  }
  useEffect(() => { load().catch(() => setLoading(false)); }, []);

  async function markReviewed(id) {
    await api.post(`/documents/${id}/mark_reviewed/`);
    load();
  }

  const totalControls = frameworks.reduce((s, f) => s + (f.control_count || 0), 0);
  const implemented = frameworks.reduce((s, f) => s + (f.implemented_count || 0), 0);
  const overdue = reviews.filter((r) => r.days_until_review < 0).length;
  const pct = totalControls ? Math.round((implemented / totalControls) * 100) : 0;

  const risks = summary?.risks;
  const cov = summary?.controls;
  const covPct = cov && cov.total ? Math.round((cov.with_evidence / cov.total) * 100) : 0;

  if (loading) return <div className="loading">Loading dashboard…</div>;

  return (
    <>
      <div className="stat-row">
        <div className="stat">
          <div className="k">Frameworks</div>
          <div className="v">{frameworks.length}</div>
          <div className="sub">{frameworks.map((f) => f.name).join(" · ")}</div>
        </div>
        <div className="stat">
          <div className="k">Controls implemented</div>
          <div className="v">{implemented}<span style={{ fontSize: 16, color: "var(--muted)" }}>/{totalControls}</span></div>
          <div className="progress" style={{ marginTop: 8 }}><span style={{ width: `${pct}%` }} /></div>
        </div>
        <div className="stat">
          <div className="k">Documents</div>
          <div className="v">{docCount}</div>
          <div className="sub">Policies, procedures & evidence</div>
        </div>
        <div className="stat">
          <div className="k">Reviews overdue</div>
          <div className={"v" + (overdue ? " alert" : "")}>{overdue}</div>
          <div className="sub">{reviews.length} due within 120 days</div>
        </div>
      </div>

      {summary && (
        <div className="stat-row" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="stat">
            <div className="k">Risk posture</div>
            <div className="v">
              {(risks?.open ?? 0)}
              <span style={{ fontSize: 14, color: "var(--muted)", marginLeft: 6 }}>open</span>
              {risks?.overdue > 0 && (
                <span style={{ fontSize: 14, color: "var(--red)", marginLeft: 12 }}>{risks.overdue} overdue</span>
              )}
            </div>
            <div className="sub">Open and mitigating risks in the register</div>
          </div>
          <div className="stat">
            <div className="k">Evidence coverage</div>
            <div className="v">
              {covPct}%
              <span style={{ fontSize: 14, color: "var(--muted)", marginLeft: 8 }}>
                {cov?.with_evidence ?? 0}/{cov?.total ?? 0} controls
              </span>
            </div>
            <div className="progress" style={{ marginTop: 8 }}><span style={{ width: `${covPct}%` }} /></div>
            <div className="sub">{cov?.evidence_links ?? 0} control–document links</div>
          </div>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <div className="card-head"><h2>Compliance calendar</h2><span className="eyebrow">reviews · audits · tasks</span></div>
          <div className="card-body"><Calendar events={events} /></div>
        </div>

        <div className="card">
          <div className="card-head"><h2>Reviews coming up</h2><span className="eyebrow">next 120 days</span></div>
          <div className="card-body">
            {reviews.length === 0 && <div className="empty">Nothing due. You're all caught up.</div>}
            {reviews.slice(0, 8).map((r) => (
              <div className="review-item" key={r.id}>
                {reviewBadge(r.days_until_review)}
                <div className="meta">
                  <div className="name">{r.name}</div>
                  <div className="path">{r.folder_path}</div>
                </div>
                <button className="btn small" onClick={() => markReviewed(r.id)}>Mark reviewed</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
