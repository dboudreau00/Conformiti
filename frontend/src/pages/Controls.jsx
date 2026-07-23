import { useEffect, useState } from "react";
import api from "../api/client.js";

const STATUS = [
  ["not_started", "Not started", "neutral"],
  ["in_progress", "In progress", "soon"],
  ["implemented", "Implemented", "ok"],
  ["not_applicable", "N/A", "neutral"],
];
const cls = (s) => STATUS.find((x) => x[0] === s)?.[2] || "neutral";

export default function Controls({ me }) {
  const [frameworks, setFrameworks] = useState([]);
  const [active, setActive] = useState(null);
  const [controls, setControls] = useState([]);
  const [loading, setLoading] = useState(true);

  // Evidence drawer state
  const [evControl, setEvControl] = useState(null);
  const [links, setLinks] = useState([]);
  const [linksLoading, setLinksLoading] = useState(false);
  const [docChoices, setDocChoices] = useState([]);
  const [selDocs, setSelDocs] = useState([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const canManage = me?.capabilities?.manage_frameworks;
  const canLink = canManage || me?.capabilities?.manage_documents;

  useEffect(() => {
    api.get("/frameworks/").then((r) => {
      const list = r.data.results || r.data;
      setFrameworks(list);
      if (list.length) setActive(list[0].key);
    });
  }, []);

  useEffect(() => {
    if (!active) return;
    setLoading(true);
    setEvControl(null);
    api.get(`/frameworks/${active}/controls/`).then((r) => {
      setControls(r.data);
      setLoading(false);
    });
  }, [active]);

  async function setStatus(id, status) {
    setControls((cs) => cs.map((c) => (c.id === id ? { ...c, status } : c)));
    await api.patch(`/controls/${id}/`, { status });
  }

  // --- evidence drawer ------------------------------------------------------
  async function openEvidence(c) {
    if (evControl?.id === c.id) { setEvControl(null); return; }
    setEvControl(c);
    setLinks([]);
    setSelDocs([]);
    setNote("");
    setLinksLoading(true);
    const r = await api.get(`/control-evidence/?control=${c.id}`);
    setLinks(r.data.results || r.data);
    setLinksLoading(false);
    if (!docChoices.length) {
      const ch = await api.get("/control-evidence/choices/");
      setDocChoices(ch.data.documents);
    }
  }

  function bumpCount(controlId, delta) {
    setControls((cs) => cs.map((c) =>
      c.id === controlId
        ? { ...c, evidence_count: Math.max(0, (c.evidence_count || 0) + delta) }
        : c
    ));
  }

  async function attach(e) {
    e.preventDefault();
    if (!selDocs.length) return;
    setBusy(true);
    try {
      const { data } = await api.post("/control-evidence/bulk/", {
        control: evControl.id,
        documents: selDocs.map(Number),
        note,
      });
      setLinks((ls) => [...ls, ...data.created]);
      bumpCount(evControl.id, data.created.length);
      setSelDocs([]);
      setNote("");
    } finally {
      setBusy(false);
    }
  }

  async function unlink(link) {
    await api.delete(`/control-evidence/${link.id}/`);
    setLinks((ls) => ls.filter((l) => l.id !== link.id));
    bumpCount(evControl.id, -1);
  }

  const current = frameworks.find((f) => f.key === active);
  const linkedIds = new Set(links.map((l) => l.document));
  const available = docChoices.filter((d) => !linkedIds.has(d.id));

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="chips">
            {frameworks.map((f) => (
              <div key={f.key} className={"chip" + (f.key === active ? " active" : "")}
                   onClick={() => setActive(f.key)}>
                {f.name} {f.version}
              </div>
            ))}
          </div>
          {current && (
            <div className="sub" style={{ marginTop: 8 }}>
              {current.implemented_count}/{current.control_count} controls implemented ·
              {" "}{current.authority}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>{current ? `${current.name} controls` : "Controls"}</h2>
          <span className="eyebrow">{controls.length} controls</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {loading ? <div className="loading">Loading controls…</div> : (
            <table>
              <thead>
                <tr>
                  <th style={{ width: 90 }}>ID</th>
                  <th>Control</th>
                  <th style={{ width: 150 }}>Owner</th>
                  <th style={{ width: 100 }}>Evidence</th>
                  <th style={{ width: 150 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {controls.map((c) => (
                  <tr key={c.id}>
                    <td className="cid">{c.control_id}</td>
                    <td>
                      <div style={{ fontWeight: 500 }}>{c.title}</div>
                      <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{c.objective}</div>
                    </td>
                    <td style={{ color: c.owner_name ? "var(--ink)" : "var(--muted)" }}>
                      {c.owner_name || "Unassigned"}
                    </td>
                    <td>
                      <span
                        className={
                          "count-pill " + (c.evidence_count ? "has" : "none") +
                          (evControl?.id === c.id ? " open" : "")
                        }
                        onClick={() => openEvidence(c)}
                        title="Show linked evidence"
                      >
                        {c.evidence_count || 0} {c.evidence_count === 1 ? "doc" : "docs"}
                      </span>
                    </td>
                    <td>
                      {canManage ? (
                        <select value={c.status} onChange={(e) => setStatus(c.id, e.target.value)}>
                          {STATUS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                        </select>
                      ) : (
                        <span className={`badge ${cls(c.status)}`}><span className="dot" />
                          {STATUS.find((x) => x[0] === c.status)?.[1]}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {evControl && (
        <div className="card" style={{ marginTop: 18 }}>
          <div className="card-head">
            <div>
              <h2><span className="mono">{evControl.control_id}</span> · evidence</h2>
              <div className="eyebrow" style={{ marginTop: 3 }}>{evControl.title}</div>
            </div>
            <button className="btn small" onClick={() => setEvControl(null)}>Close</button>
          </div>
          <div className="card-body">
            {linksLoading ? (
              <div className="loading">Loading evidence…</div>
            ) : links.length === 0 ? (
              <div className="empty">No evidence linked to this control yet.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Document</th>
                    <th style={{ width: 220 }}>Folder</th>
                    <th style={{ width: 110 }}>Status</th>
                    <th>Note</th>
                    <th style={{ width: 130 }}>Linked by</th>
                    {canLink ? <th style={{ width: 80 }}></th> : null}
                  </tr>
                </thead>
                <tbody>
                  {links.map((l) => (
                    <tr key={l.id}>
                      <td style={{ fontWeight: 500 }}>{l.document_name}</td>
                      <td style={{ color: "var(--muted)", fontSize: 12.5 }}>{l.folder_path}</td>
                      <td>
                        <span className={"badge " + (l.document_status === "approved" ? "ok" : "neutral")}>
                          <span className="dot" />{l.document_status.replace("_", " ")}
                        </span>
                      </td>
                      <td style={{ color: "var(--muted)", fontSize: 12.5 }}>{l.note || "—"}</td>
                      <td style={{ color: "var(--muted)", fontSize: 12.5 }}>{l.linked_by_name || "—"}</td>
                      {canLink ? (
                        <td style={{ textAlign: "right" }}>
                          <button className="btn small" onClick={() => unlink(l)}>Unlink</button>
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {canLink && (
              <form onSubmit={attach}
                    style={{ display: "flex", gap: 12, alignItems: "flex-start", marginTop: 16, flexWrap: "wrap" }}>
                <div style={{ flex: "2 1 320px" }}>
                  <div className="eyebrow" style={{ marginBottom: 6 }}>
                    Attach evidence — select one or more documents
                  </div>
                  <select multiple className="doc-multi" style={{ width: "100%" }} value={selDocs}
                          onChange={(e) => setSelDocs(Array.from(e.target.selectedOptions).map((o) => o.value))}>
                    {available.map((d) => (
                      <option key={d.id} value={d.id}>{d.path} / {d.name}</option>
                    ))}
                  </select>
                </div>
                <div style={{ flex: "1 1 220px", display: "flex", flexDirection: "column", gap: 8 }}>
                  <div className="eyebrow">Note (optional)</div>
                  <input value={note} onChange={(e) => setNote(e.target.value)}
                         placeholder="Why this document applies" />
                  <button className="btn primary" disabled={busy || !selDocs.length}>
                    {busy ? "Attaching…" : "Attach " + (selDocs.length || "") + (selDocs.length === 1 ? " document" : " documents")}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
