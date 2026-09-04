import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { DownloadIcon, FileSpreadsheetIcon, PlusIcon, UploadIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { Collapse, EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Field } from "../components/risks/Field.jsx";
import { RiskDetail } from "../components/risks/RiskDetail.jsx";
import { RiskHeatmap } from "../components/risks/RiskHeatmap.jsx";
import { RiskTable } from "../components/risks/RiskTable.jsx";
import { FILTERS, IMPACT_WORDS, LIKELIHOOD_WORDS, SCALE, TEMPLATE_CSV, TYPES, deriveSummary, filterRisks } from "../components/risks/vocab.js";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Chip } from "../components/ui/SegmentedControl.jsx";
import { useShell } from "../shell.js";
import { cn } from "../utils/cn.js";
import { errorText } from "../utils/a11y.js";

const displayName = (u) => u.full_name || u.username || `User ${u.id}`;

export default function Risks({ me }) {
  const { refreshCounts } = useShell();
  const [risks, setRisks] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [users, setUsers] = useState([]);
  const [usersErr, setUsersErr] = useState("");
  const [controls, setControls] = useState([]);
  const [filter, setFilter] = useState("live");
  const [selectedId, setSelectedId] = useState(null);
  const [notes, setNotes] = useState([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesErr, setNotesErr] = useState("");
  const [addingNote, setAddingNote] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);
  const [banner, setBanner] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const fileRef = useRef(null);

  const canManage = !!me?.capabilities?.manage_frameworks;
  const canEditRisk = (r) => canManage || (r?.owner != null && r.owner === me?.id);
  const selected = risks.find((r) => r.id === selectedId) || null;

  const loadSummary = useCallback(async (fallbackRisks) => {
    try {
      const { data } = await api.get("/risks/summary/");
      setSummary(data);
    } catch {
      setSummary(deriveSummary(fallbackRisks || []));
    }
  }, []);

  const loadRisks = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const all = await fetchAll("/risks/");
      setRisks(all);
      await loadSummary(all);
    } catch (e) {
      setError(errorText(e, "Couldn't load the risk register."));
    } finally {
      setLoading(false);
    }
  }, [loadSummary]);

  useEffect(() => {
    loadRisks();
    fetchAll("/users/").then(setUsers).catch((e) => setUsersErr(errorText(e, "Owner directory unavailable.")));
    api.get("/control-evidence/choices/").then((r) => setControls(r.data.controls || [])).catch(() => setControls([]));
  }, [loadRisks]);

  // Notes for the selected risk.
  useEffect(() => {
    if (!selectedId) return;
    let alive = true;
    setNotes([]);
    setNotesErr("");
    setNotesLoading(true);
    setNotice(null);
    api
      .get(`/risk-notes/?risk=${selectedId}`)
      .then((r) => alive && setNotes(r.data.results || r.data))
      .catch((e) => alive && setNotesErr(errorText(e, "Couldn't load the notes.")))
      .finally(() => alive && setNotesLoading(false));
    return () => { alive = false; };
  }, [selectedId]);

  function applyUpdate(updated) {
    setRisks((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
  }

  async function patch(payload) {
    if (!selected) return;
    setSaving(true);
    setNotice(null);
    try {
      const { data } = await api.patch(`/risks/${selected.id}/`, payload);
      applyUpdate(data);
      await loadSummary();
      refreshCounts();
      setNotice({ ok: true, text: "Saved." });
    } catch (e) {
      setNotice({ ok: false, text: errorText(e, "Couldn't save that change.") });
    } finally {
      setSaving(false);
    }
  }

  async function addNote(text) {
    if (!selected) return false;
    setAddingNote(true);
    setNotesErr("");
    try {
      const { data } = await api.post("/risk-notes/", { risk: selected.id, text });
      setNotes((ns) => [...ns, data]);
      setRisks((rs) => rs.map((r) => (r.id === selected.id ? { ...r, note_count: (r.note_count || 0) + 1 } : r)));
      return true;
    } catch (e) {
      setNotesErr(errorText(e, "Couldn't add the note."));
      return false;
    } finally {
      setAddingNote(false);
    }
  }

  async function createRisk(e) {
    e.preventDefault();
    const f = e.target;
    const payload = {
      title: f.title.value.trim(),
      risk_type: f.rtype.value,
      likelihood: Number(f.likelihood.value),
      impact: Number(f.impact.value),
      owner: f.owner.value ? Number(f.owner.value) : null,
      control: f.control.value ? Number(f.control.value) : null,
      due_date: f.due.value || null,
      description: f.description.value,
      mitigation_plan: f.plan.value,
    };
    if (!payload.title) return;
    setCreating(true);
    setBanner(null);
    try {
      const { data } = await api.post("/risks/", payload);
      setRisks((rs) => [data, ...rs]);
      await loadSummary();
      refreshCounts();
      setShowNew(false);
      f.reset();
      setSelectedId(data.id);
      setBanner({ ok: true, text: `Risk #${data.id} created.` });
    } catch (err) {
      setBanner({ ok: false, text: errorText(err, "Couldn't create the risk.") });
    } finally {
      setCreating(false);
    }
  }

  async function doImport(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setImporting(true);
    setImportResult(null);
    setBanner(null);
    try {
      const { data } = await api.post("/risks/import/", fd);
      setImportResult(data);
      await loadRisks();
      refreshCounts();
    } catch (err) {
      setImportResult({ error: errorText(err, "Import failed.") });
    } finally {
      setImporting(false);
    }
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([TEMPLATE_CSV], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "risk-import-template.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function exportCsv() {
    setBanner(null);
    try {
      await downloadFile("/risks/export/", "risk-register.csv");
    } catch (err) {
      setBanner({ ok: false, text: errorText(err, "Couldn't export the register.") });
    }
  }

  const stats = summary || deriveSummary(risks);
  const shown = filterRisks(risks, filter);
  const chipMeta = {
    live: { label: "live", count: stats.open + stats.mitigating },
    overdue: { label: "overdue", count: stats.overdue, tone: stats.overdue ? "danger" : undefined },
    severe: { label: "high / critical", count: (stats.by_rating?.high || 0) + (stats.by_rating?.critical || 0), tone: "warning" },
    closed: { label: "closed", count: stats.closed, tone: "success" },
    all: { label: "all", count: risks.length },
  };

  return (
    <PanelTransition>
      <Stack className="flex flex-col gap-4">
        <StackItem className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter the register">
            {FILTERS.map((key) => (
              <Chip key={key} active={filter === key} onClick={() => setFilter(key)} tone={chipMeta[key].tone} count={chipMeta[key].count}>
                {chipMeta[key].label}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={downloadTemplate} icon={<FileSpreadsheetIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
              Template
            </Button>
            {canManage ? (
              <>
                <input ref={fileRef} type="file" accept=".csv,.xlsx" className="hidden" onChange={doImport} aria-label="Import risks from CSV or XLSX" />
                <Button size="sm" onClick={() => fileRef.current?.click()} disabled={importing} icon={<UploadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                  {importing ? "Importing…" : "Import CSV/XLSX"}
                </Button>
              </>
            ) : null}
            <Button size="sm" onClick={exportCsv} icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
              Export
            </Button>
            {canManage ? (
              <Button size="sm" variant="primary" onClick={() => setShowNew((v) => !v)} aria-expanded={showNew} icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden="true" />}>
                {showNew ? "Cancel" : "New risk"}
              </Button>
            ) : null}
          </div>
        </StackItem>

        {banner ? (
          <StackItem>
            <div className={cn("notice", banner.ok ? "notice-ok" : "notice-err")} role={banner.ok ? "status" : "alert"}>
              {banner.text}
            </div>
          </StackItem>
        ) : null}

        <AnimatePresence initial={false}>
          {importResult ? (
            <motion.div key="import" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2, ease: EASE }}>
              <Panel>
                <PanelHeader title="Import result">
                  <Button size="sm" variant="ghost" onClick={() => setImportResult(null)}>Dismiss</Button>
                </PanelHeader>
                <div className="p-5 text-[13px]">
                  {importResult.error ? (
                    <div className="notice notice-err" role="alert">{importResult.error}</div>
                  ) : (
                    <>
                      <p className="text-ink">
                        <span className="tabular font-semibold">{importResult.created}</span> risk{importResult.created === 1 ? "" : "s"} created
                        {importResult.skipped?.length ? <> · {importResult.skipped.length} skipped</> : null}
                        {importResult.warnings?.length ? <> · {importResult.warnings.length} warning{importResult.warnings.length === 1 ? "" : "s"}</> : null}
                      </p>
                      {importResult.skipped?.slice(0, 8).map((s, i) => (
                        <p key={`s${i}`} className="mt-1.5 text-xs text-muted">Row {s.row}: {s.title} — {s.reason}</p>
                      ))}
                      {importResult.warnings?.length ? (
                        <div className="notice notice-warn mt-3">
                          {importResult.warnings.slice(0, 10).map((w, i) => (
                            <p key={`w${i}`} className="text-xs">Row {w.row}: {w.message}</p>
                          ))}
                          {importResult.warnings.length > 10 ? <p className="mt-1 text-2xs">+{importResult.warnings.length - 10} more</p> : null}
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
              </Panel>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {showNew && canManage ? (
            <Collapse key="new" open>
              <Panel>
                <PanelHeader title="New risk" meta="Register entry" />
                <form onSubmit={createRisk} className="grid grid-cols-1 gap-3 p-5 md:grid-cols-4" aria-busy={creating}>
                  <Field id="new-title" label="Title" className="md:col-span-2">
                    <input id="new-title" name="title" className="input" required maxLength={255} placeholder="e.g. Laptops without disk encryption" />
                  </Field>
                  <Field id="new-type" label="Type">
                    <select id="new-type" name="rtype" className="input" defaultValue="control_gap">
                      {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </Field>
                  <Field id="new-due" label="Due date">
                    <input id="new-due" name="due" type="date" className="input" />
                  </Field>
                  <Field id="new-likelihood" label="Likelihood">
                    <select id="new-likelihood" name="likelihood" className="input" defaultValue="3">
                      {SCALE.map((n) => <option key={n} value={n}>{n} · {LIKELIHOOD_WORDS[n - 1]}</option>)}
                    </select>
                  </Field>
                  <Field id="new-impact" label="Impact">
                    <select id="new-impact" name="impact" className="input" defaultValue="3">
                      {SCALE.map((n) => <option key={n} value={n}>{n} · {IMPACT_WORDS[n - 1]}</option>)}
                    </select>
                  </Field>
                  <Field id="new-owner" label="Owner">
                    <select id="new-owner" name="owner" className="input" defaultValue="">
                      <option value="">Unassigned</option>
                      {users.map((u) => <option key={u.id} value={u.id}>{displayName(u)}</option>)}
                    </select>
                  </Field>
                  <Field id="new-control" label="Related control">
                    <select id="new-control" name="control" className="input" defaultValue="">
                      <option value="">None</option>
                      {controls.map((c) => <option key={c.id} value={c.id}>{c.framework_name} · {c.label}</option>)}
                    </select>
                  </Field>
                  <Field id="new-description" label="Description" className="md:col-span-4">
                    <textarea id="new-description" name="description" className="input" rows={2} placeholder="What is exposed, and how" />
                  </Field>
                  <Field id="new-plan" label="Mitigation plan" className="md:col-span-4">
                    <textarea id="new-plan" name="plan" className="input" rows={2} placeholder="How it will be reduced, transferred or avoided" />
                  </Field>
                  <div className="flex gap-2 md:col-span-4">
                    <Button type="submit" variant="primary" disabled={creating}>{creating ? "Creating…" : "Create risk"}</Button>
                    <Button type="button" variant="ghost" onClick={() => setShowNew(false)}>Cancel</Button>
                  </div>
                </form>
              </Panel>
            </Collapse>
          ) : null}
        </AnimatePresence>

        <StackItem className="grid grid-cols-12 gap-4">
          <div className="col-span-12 xl:col-span-7">
            <Panel className="overflow-hidden">
              <PanelHeader title="Risk register" meta={loading ? "Loading" : `${shown.length} shown · ${risks.length} total`} />
              {loading ? (
                <Loading>Loading risks…</Loading>
              ) : error ? (
                <div className="p-5">
                  <div className="notice notice-err" role="alert">{error}</div>
                  <Button size="sm" className="mt-3" onClick={loadRisks}>Try again</Button>
                </div>
              ) : shown.length === 0 ? (
                <Empty title="No risks in this view">{risks.length ? "Widen the filter above." : canManage ? "Create the first entry or import a register." : "Nothing has been logged yet."}</Empty>
              ) : (
                <RiskTable risks={shown} selectedId={selectedId} onSelect={(r) => setSelectedId((cur) => (cur === r.id ? null : r.id))} />
              )}
            </Panel>
          </div>
          <div className="col-span-12 xl:col-span-5">
            <RiskHeatmap risks={risks} stats={stats} loading={loading} selectedId={selectedId} onSelect={(r) => setSelectedId(r.id)} />
          </div>
        </StackItem>

        <AnimatePresence initial={false}>
          {selected ? (
            <motion.div key={`detail-${selected.id}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22, ease: EASE }}>
              <RiskDetail
                risk={selected}
                canEdit={canEditRisk(selected)}
                users={users}
                usersErr={usersErr}
                saving={saving}
                notice={notice}
                onPatch={patch}
                onClose={() => setSelectedId(null)}
                notes={notes}
                notesLoading={notesLoading}
                notesErr={notesErr}
                addingNote={addingNote}
                onAddNote={addNote}
              />
            </motion.div>
          ) : null}
        </AnimatePresence>

        {!loading && !error ? (
          <StackItem>
            <Label className="block px-1">
              Ratings use the 5×5 banding: 1–4 low · 5–9 moderate · 10–15 high · 16–25 critical. Owners may edit their own risks; framework managers may edit, create, import and delete.
            </Label>
          </StackItem>
        ) : null}
      </Stack>
    </PanelTransition>
  );
}
