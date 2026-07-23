import { useEffect, useState } from "react";
import api from "../api/client.js";

/* Status palettes kept in sync with the design tokens. */
const CONTROL_COLORS = {
  not_started: "#c3ccd5",
  in_progress: "#b45309",
  implemented: "#0f766e",
  not_applicable: "#8595a4",
};
const CONTROL_LABELS = {
  not_started: "Not started",
  in_progress: "In progress",
  implemented: "Implemented",
  not_applicable: "Not applicable",
};
const DOC_COLORS = {
  draft: "#c3ccd5",
  in_review: "#b45309",
  approved: "#0f766e",
  expired: "#b91c1c",
};
const DOC_LABELS = {
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  expired: "Expired",
};

/* --- pure-SVG donut ------------------------------------------------------ */
function Donut({ segments, centerTop, centerBottom, size = 150 }) {
  const stroke = 20;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef1f4" strokeWidth={stroke} />
          {segments.map((seg, i) => {
            const len = (seg.value / total) * c;
            const circle = (
              <circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={seg.color}
                strokeWidth={stroke}
                strokeDasharray={`${len} ${c - len}`}
                strokeDashoffset={-offset}
              />
            );
            offset += len;
            return circle;
          })}
        </g>
        <text x="50%" y="47%" textAnchor="middle" className="donut-top">{centerTop}</text>
        <text x="50%" y="62%" textAnchor="middle" className="donut-bottom">{centerBottom}</text>
      </svg>
    </div>
  );
}

function Legend({ items }) {
  return (
    <div className="legend">
      {items.map((it) => (
        <div className="legend-item" key={it.label}>
          <span className="sw" style={{ background: it.color }} />
          <span className="legend-label">{it.label}</span>
          <span className="legend-val mono">{it.value}</span>
        </div>
      ))}
    </div>
  );
}

/* --- horizontal stacked bar (per-framework control mix) ------------------ */
function StackedBar({ byStatus }) {
  const total = Object.values(byStatus).reduce((s, x) => s + x, 0) || 1;
  return (
    <div className="stacked">
      {Object.keys(CONTROL_COLORS).map((k) =>
        byStatus[k] ? (
          <span
            key={k}
            className="seg"
            style={{ width: `${(byStatus[k] / total) * 100}%`, background: CONTROL_COLORS[k] }}
            title={`${CONTROL_LABELS[k]}: ${byStatus[k]}`}
          />
        ) : null
      )}
    </div>
  );
}

/* --- vertical timeline bars (upcoming reviews by month) ------------------ */
function TimelineBars({ data }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div className="timeline">
      {data.map((d) => (
        <div className="tl-col" key={d.month}>
          <div className="tl-bar-wrap">
            <div className="tl-val mono">{d.count || ""}</div>
            <div className="tl-bar" style={{ height: `${(d.count / max) * 100}%` }} />
          </div>
          <div className="tl-label mono">{d.month}</div>
        </div>
      ))}
    </div>
  );
}

/* --- ownership coverage meter -------------------------------------------- */
function Coverage({ label, owned, total }) {
  const pct = total ? Math.round((owned / total) * 100) : 0;
  return (
    <div className="coverage">
      <div className="cov-head">
        <span>{label}</span>
        <span className="mono">{owned}/{total} · {pct}%</span>
      </div>
      <div className="progress"><span style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export default function Analytics() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get("/analytics/summary/").then((r) => setData(r.data)).catch(() => setErr(true));
  }, []);

  if (err) return <div className="empty">Couldn't load analytics.</div>;
  if (!data) return <div className="loading">Crunching analytics…</div>;

  const cs = data.controls.by_status;
  const applicable = data.controls.total - cs.not_applicable;
  const readiness = applicable ? Math.round((cs.implemented / applicable) * 100) : 0;
  const ds = data.documents.by_status;

  return (
    <>
      <div className="stat-row">
        <div className="stat">
          <div className="k">Overall readiness</div>
          <div className="v">{readiness}<span style={{ fontSize: 16, color: "var(--muted)" }}>%</span></div>
          <div className="progress" style={{ marginTop: 8 }}><span style={{ width: `${readiness}%` }} /></div>
        </div>
        <div className="stat">
          <div className="k">Controls implemented</div>
          <div className="v">{cs.implemented}<span style={{ fontSize: 16, color: "var(--muted)" }}>/{applicable}</span></div>
          <div className="sub">{cs.not_applicable} marked N/A</div>
        </div>
        <div className="stat">
          <div className="k">Documents approved</div>
          <div className="v">{ds.approved}<span style={{ fontSize: 16, color: "var(--muted)" }}>/{data.documents.total}</span></div>
          <div className="sub">{ds.expired} expired · {ds.in_review} in review</div>
        </div>
        <div className="stat">
          <div className="k">Reviews overdue</div>
          <div className={"v" + (data.reviews.overdue ? " alert" : "")}>{data.reviews.overdue}</div>
          <div className="sub">{data.reviews.due_30} due in 30d · {data.reviews.scheduled} scheduled</div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-head"><h2>Framework readiness</h2><span className="eyebrow">implemented ÷ applicable</span></div>
        <div className="card-body">
          {data.frameworks.map((f) => (
            <div className="fw-row" key={f.key}>
              <div className="fw-top">
                <span className="fw-name">{f.name}</span>
                <span className="fw-pct mono">{f.pct}% · {f.implemented}/{f.applicable}</span>
              </div>
              <StackedBar byStatus={f.by_status} />
            </div>
          ))}
          <Legend
            items={Object.keys(CONTROL_COLORS).map((k) => ({
              label: CONTROL_LABELS[k], color: CONTROL_COLORS[k], value: cs[k],
            }))}
          />
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head"><h2>Control status</h2><span className="eyebrow">{data.controls.with_evidence ?? 0}/{data.controls.total} have evidence</span></div>
          <div className="card-body chart-split">
            <Donut
              size={150}
              centerTop={String(data.controls.total)}
              centerBottom="controls"
              segments={Object.keys(CONTROL_COLORS).map((k) => ({ value: cs[k], color: CONTROL_COLORS[k] }))}
            />
            <Legend
              items={Object.keys(CONTROL_COLORS).map((k) => ({
                label: CONTROL_LABELS[k], color: CONTROL_COLORS[k], value: cs[k],
              }))}
            />
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h2>Document status</h2><span className="eyebrow">visible to you</span></div>
          <div className="card-body chart-split">
            <Donut
              size={150}
              centerTop={String(data.documents.total)}
              centerBottom="documents"
              segments={Object.keys(DOC_COLORS).map((k) => ({ value: ds[k], color: DOC_COLORS[k] }))}
            />
            <Legend
              items={Object.keys(DOC_COLORS).map((k) => ({
                label: DOC_LABELS[k], color: DOC_COLORS[k], value: ds[k],
              }))}
            />
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 20 }}>
        <div className="card">
          <div className="card-head"><h2>Upcoming reviews</h2><span className="eyebrow">next 6 months</span></div>
          <div className="card-body"><TimelineBars data={data.review_timeline} /></div>
        </div>

        <div className="card">
          <div className="card-head"><h2>Ownership coverage</h2><span className="eyebrow">assigned owners</span></div>
          <div className="card-body">
            <Coverage label="Controls with an owner" owned={data.controls.owned} total={data.controls.total} />
            <Coverage label="Documents with an owner" owned={data.documents.owned} total={data.documents.total} />
            <div className="cov-note">Unassigned items have no one accountable for keeping evidence current.</div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 20 }}>
        <div className="card-head"><h2>Most overdue documents</h2><span className="eyebrow">oldest review dates</span></div>
        <div className="card-body">
          {data.overdue_sample.length === 0 && <div className="empty">No overdue documents. Nicely kept.</div>}
          {data.overdue_sample.map((d) => (
            <div className="review-item" key={d.id}>
              <span className="badge overdue"><span className="dot" />{d.days_overdue}d</span>
              <div className="meta">
                <div className="name">{d.name}</div>
                <div className="path">{d.folder_path}</div>
              </div>
              <span className="owner-tag mono">{d.owner || "unassigned"}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
