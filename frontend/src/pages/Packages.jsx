import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  DownloadIcon,
  FileTextIcon,
  LockIcon,
  UserPlusIcon,
  XIcon,
} from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import DocumentViewer from "../components/documents/DocumentViewer.jsx";
import { PanelTransition } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";

const EASE = [0.23, 1, 0.32, 1];

const PACKAGE_STATUS = {
  draft: { label: "Draft", tone: "warning" },
  sealed: { label: "Sealed", tone: "success" },
  withdrawn: { label: "Withdrawn", tone: "muted" },
};

const CONCLUSION = {
  pending: { label: "Not concluded", tone: "faint" },
  no_exceptions: { label: "No exceptions", tone: "success" },
  exceptions: { label: "Exceptions noted", tone: "danger" },
  not_tested: { label: "Not tested", tone: "muted" },
};

const ASSURANCE = [
  ["readiness", "Readiness assessment"],
  ["type_i", "SOC 2 Type I"],
  ["type_ii", "SOC 2 Type II"],
  ["iso_stage_1", "ISO 27001 Stage 1"],
  ["iso_stage_2", "ISO 27001 Stage 2"],
  ["iso_surveillance", "ISO 27001 surveillance"],
  ["pci_roc", "PCI DSS Report on Compliance"],
  ["internal", "Internal audit"],
];

function Notice({ msg }) {
  if (!msg) return null;
  return (
    <p className={cn("notice", msg.ok ? "notice-ok" : "notice-err")} role="status">
      {msg.text}
    </p>
  );
}

export default function Packages({ me }) {
  const [packages, setPackages] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [rows, setRows] = useState([]);
  const [grants, setGrants] = useState([]);
  const [integrity, setIntegrity] = useState(null);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ name: "", engagement: "", audit_firm: "", assurance_type: "type_ii" });
  const [viewing, setViewing] = useState(null);

  // Pinned evidence opens through the package's own preview route, so the
  // auditor's grant — not folder permissions — is what admits them.
  const openEvidence = (e) => setViewing({
    title: e.document_name,
    subtitle: `Pinned v${e.pinned_version} in ${selected?.name || "this package"}`,
    previewUrl: `/package-evidence/${e.id}/preview/`,
    downloadUrl: e.download_url,
    filename: e.document_name,
    facts: [
      { label: "Pinned version", value: `v${e.pinned_version}` },
      { label: "Digest recorded at sealing (SHA-256)", value: e.content_sha256, mono: true },
    ],
  });

  const canAssemble = !!(me?.is_superuser || me?.capabilities?.includes?.("frameworks")
    || me?.role_detail?.can_manage_frameworks);

  const selected = useMemo(
    () => (packages || []).find((p) => p.id === selectedId) || null,
    [packages, selectedId]
  );

  async function loadPackages(keep = selectedId) {
    const data = await fetchAll("/evidence-packages/");
    setPackages(data);
    const next = data.find((p) => p.id === keep) || data[0] || null;
    setSelectedId(next ? next.id : null);
  }

  useEffect(() => {
    loadPackages().catch((e) => {
      setPackages([]);
      setMsg({ ok: false, text: errorText(e, "Couldn't load evidence packages.") });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setRows([]);
      setGrants([]);
      setIntegrity(null);
      return;
    }
    let live = true;
    (async () => {
      const [controls, issued] = await Promise.all([
        fetchAll(`/package-controls/?package=${selectedId}`),
        fetchAll(`/package-grants/?package=${selectedId}`),
      ]);
      if (!live) return;
      setRows(controls);
      setGrants(issued);
      try {
        const { data } = await api.get(`/evidence-packages/${selectedId}/verify/`);
        if (live) setIntegrity(data);
      } catch {
        if (live) setIntegrity(null);
      }
    })().catch(() => {});
    return () => { live = false; };
  }, [selectedId]);

  async function act(kind, fn, okText) {
    setBusy(kind);
    setMsg(null);
    try {
      await fn();
      if (okText) setMsg({ ok: true, text: okText });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const createPackage = (e) => {
    e.preventDefault();
    return act("create", async () => {
      const { data } = await api.post("/evidence-packages/", draft);
      setCreating(false);
      setDraft({ name: "", engagement: "", audit_firm: "", assurance_type: "type_ii" });
      await loadPackages(data.id);
    }, "Package opened. Add the controls in scope, then seal it.");
  };

  const seal = () => {
    const assertion = window.prompt(
      "Management assertion — the statement the auditor relies on (40 characters minimum):",
      "Management asserts that the controls described in this package were designed and "
      + "implemented as described, and that the evidence attached is complete and accurate."
    );
    if (!assertion) return;
    return act("seal", async () => {
      await api.post(`/evidence-packages/${selectedId}/seal/`, { assertion });
      await loadPackages();
    }, "Sealed. The manifest digest is now fixed — publish it to the auditor separately.");
  };

  const withdraw = () => {
    const reason = window.prompt("Why is this package being withdrawn?", "Fieldwork complete");
    if (reason === null) return;
    return act("withdraw", async () => {
      await api.post(`/evidence-packages/${selectedId}/withdraw/`, { reason });
      await loadPackages();
    }, "Withdrawn. Every grant is revoked; the record remains.");
  };

  const exportBundle = () =>
    act("export", () =>
      downloadFile(`/evidence-packages/${selectedId}/export/`,
        `${(selected?.name || "evidence-package").replace(/[^\w-]+/g, "-")}.zip`));

  const conclude = (row, field, value) =>
    act(`row-${row.id}`, async () => {
      const body = { [field]: value };
      if (value === "not_tested") {
        const reason = window.prompt("Why was this control not tested?");
        if (!reason) return;
        body.not_tested_reason = reason;
      }
      await api.patch(`/package-controls/${row.id}/`, body);
      setRows(await fetchAll(`/package-controls/?package=${selectedId}`));
    });

  if (packages === null) {
    return (
      <PanelTransition>
        <Panel><Loading /></Panel>
      </PanelTransition>
    );
  }

  return (
    <PanelTransition>
    <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
      {/* ---------------------------------------------------------- list */}
      <div className="flex flex-col gap-4">
        <Panel className="overflow-hidden">
          <PanelHeader title="Evidence packages" meta={`${packages.length} total`} />
          {packages.length === 0 ? (
            <Empty title="No packages yet">
              {canAssemble
                ? "Assemble the controls and evidence for an audit, seal it, and issue it to the auditor."
                : "Packages issued to you will appear here."}
            </Empty>
          ) : (
            <ul className="divide-y divide-line">
              {packages.map((p) => {
                const tone = PACKAGE_STATUS[p.status] || PACKAGE_STATUS.draft;
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(p.id)}
                      aria-current={p.id === selectedId || undefined}
                      className={cn(
                        "block w-full px-4 py-3 text-left transition-colors duration-150 ease-out",
                        p.id === selectedId ? "bg-accent/10" : "hover:bg-surface-2"
                      )}
                    >
                      <span className="block truncate text-[13px] font-medium text-ink">{p.name}</span>
                      <span className="mt-1 flex items-center gap-2">
                        <Badge tone={tone.tone} dot>{tone.label}</Badge>
                        <Label>{p.control_count} controls · {p.evidence_count} files</Label>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        {canAssemble ? (
          <Panel className="p-4">
            {creating ? (
              <form onSubmit={createPackage} className="grid gap-2.5">
                <div>
                  <label className="field-label" htmlFor="pkg-name">Name</label>
                  <input id="pkg-name" className="input" required value={draft.name}
                         placeholder="SOC 2 Type II fieldwork"
                         onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                </div>
                <div>
                  <label className="field-label" htmlFor="pkg-engagement">Engagement</label>
                  <input id="pkg-engagement" className="input" value={draft.engagement}
                         onChange={(e) => setDraft({ ...draft, engagement: e.target.value })} />
                </div>
                <div>
                  <label className="field-label" htmlFor="pkg-firm">Audit firm</label>
                  <input id="pkg-firm" className="input" value={draft.audit_firm}
                         onChange={(e) => setDraft({ ...draft, audit_firm: e.target.value })} />
                </div>
                <div>
                  <label className="field-label" htmlFor="pkg-assurance">Assurance type</label>
                  <select id="pkg-assurance" className="input" value={draft.assurance_type}
                          onChange={(e) => setDraft({ ...draft, assurance_type: e.target.value })}>
                    {ASSURANCE.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </div>
                <div className="mt-1 flex gap-2">
                  <Button type="submit" variant="primary" size="sm" disabled={busy === "create"}>
                    {busy === "create" ? "Opening…" : "Open package"}
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setCreating(false)}>
                    Cancel
                  </Button>
                </div>
              </form>
            ) : (
              <Button variant="primary" size="sm" className="w-full" onClick={() => setCreating(true)}>
                New package
              </Button>
            )}
          </Panel>
        ) : null}
      </div>

      {/* -------------------------------------------------------- detail */}
      <div className="flex min-w-0 flex-col gap-4">
        <Notice msg={msg} />
        {!selected ? (
          <Panel>
            <Empty title="Select a package">
              Pick a package on the left to see its controls, its evidence and who it was issued to.
            </Empty>
          </Panel>
        ) : (
          <>
            <Panel className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-[15px] font-semibold text-ink">{selected.name}</h2>
                  <p className="mt-0.5 text-xs text-muted">
                    {selected.assurance_type_display}
                    {selected.engagement ? ` · ${selected.engagement}` : ""}
                    {selected.audit_firm ? ` · ${selected.audit_firm}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {canAssemble && selected.status === "draft" ? (
                    <Button size="sm" variant="primary" onClick={seal} disabled={busy === "seal"}
                            icon={<LockIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                      {busy === "seal" ? "Sealing…" : "Seal"}
                    </Button>
                  ) : null}
                  {selected.status !== "draft" ? (
                    <Button size="sm" onClick={exportBundle} disabled={busy === "export"}
                            icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                      {busy === "export" ? "Building…" : "Export bundle"}
                    </Button>
                  ) : null}
                  {canAssemble && selected.status === "sealed" ? (
                    <Button size="sm" variant="danger" onClick={withdraw} disabled={busy === "withdraw"}>
                      Withdraw
                    </Button>
                  ) : null}
                </div>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <StatCard label="Controls" value={selected.control_count} />
                <StatCard label="Evidence files" value={selected.evidence_count} />
                <StatCard
                  label="Integrity"
                  value={integrity ? (integrity.ok ? "OK" : `${integrity.discrepancies.length}`) : "—"}
                  detail={integrity
                    ? (integrity.ok
                        ? "Every file matches what was sealed"
                        : "File(s) no longer match what was sealed")
                    : "Not checked"}
                  tone={integrity ? (integrity.ok ? "success" : "danger") : "muted"}
                />
              </div>

              {selected.manifest_sha256 ? (
                <div className="mt-4 rounded-xl border border-line bg-surface-2 p-3">
                  <Label as="p">Manifest digest (SHA-256)</Label>
                  <p className="mt-1 break-all font-mono text-2xs text-ink">{selected.manifest_sha256}</p>
                  <p className="mt-1.5 text-xs text-muted">
                    Publish this to the auditor separately. It is what lets them prove the bundle
                    they hold is the one you sealed. The bundle carries no signature, so this
                    digest and the audit-trail entry beside it are the binding to a moment.
                  </p>
                </div>
              ) : null}

              {selected.assertion ? (
                <div className="mt-3">
                  <Label as="p">Management assertion</Label>
                  <p className="mt-1 whitespace-pre-line text-[13px] leading-snug text-muted">
                    {selected.assertion}
                  </p>
                  <Label as="p" className="mt-1.5">
                    {selected.asserted_by_name} · {selected.sealed_at?.slice(0, 10)}
                  </Label>
                </div>
              ) : null}
            </Panel>

            {/* -------------------------------------------------- grants */}
            <Panel className="overflow-hidden">
              <PanelHeader title="Issued to" meta={`${grants.filter((g) => g.is_live).length} live`}>
                {canAssemble && selected.status === "sealed" ? (
                  <IssueForm packageId={selected.id} onDone={async () => {
                    setGrants(await fetchAll(`/package-grants/?package=${selected.id}`));
                    await loadPackages();
                  }} onError={(text) => setMsg({ ok: false, text })} />
                ) : null}
              </PanelHeader>
              {grants.length === 0 ? (
                <Empty title="Not issued yet">
                  Seal the package, then issue it to the auditor's account. They will see exactly
                  these files and nothing else, until the access expires or you withdraw it.
                </Empty>
              ) : (
                <ul className="divide-y divide-line">
                  {grants.map((g) => (
                    <li key={g.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                      <span className="min-w-0">
                        <span className="block truncate text-[13px] font-medium text-ink">
                          {g.full_name || g.username}
                        </span>
                        <Label className="block">
                          {g.is_live ? `until ${g.expires_at?.slice(0, 10)}` : "revoked"}
                          {g.access_count ? ` · ${g.access_count} file read(s)` : ""}
                        </Label>
                      </span>
                      <span className="flex items-center gap-2">
                        <Badge tone={g.is_live ? "success" : "muted"} dot>
                          {g.is_live ? "Live" : "Closed"}
                        </Badge>
                        {canAssemble && g.is_live ? (
                          <Button size="sm" variant="ghost" onClick={() => act(`revoke-${g.id}`, async () => {
                            await api.delete(`/package-grants/${g.id}/`);
                            setGrants(await fetchAll(`/package-grants/?package=${selected.id}`));
                          }, "Access revoked.")}>
                            Revoke
                          </Button>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            {/* ------------------------------------------------ workpaper */}
            <Panel className="overflow-hidden">
              <PanelHeader title="Controls in scope" meta={`${rows.length} rows`} />
              {rows.length === 0 ? (
                <Empty title="No controls yet">
                  {canAssemble
                    ? "Add controls from the Controls page, or POST their ids to add_controls."
                    : "This package has no controls."}
                </Empty>
              ) : (
                <ul className="divide-y divide-line">
                  <AnimatePresence initial={false}>
                    {rows.map((row, i) => (
                      <motion.li
                        key={row.id}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2, ease: EASE, delay: Math.min(i, 10) * 0.02 }}
                        className="px-5 py-3.5"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <span className="min-w-0">
                            <span className="block text-[13px] font-medium text-ink">
                              <span className="font-mono text-xs text-muted">{row.control_ref}</span>{" "}
                              {row.title}
                            </span>
                            <Label className="block">
                              {row.framework_name} · {row.category_name} · {row.mgmt_status_display}
                            </Label>
                          </span>
                          <span className="flex flex-wrap items-center gap-1.5">
                            <Badge tone={(CONCLUSION[row.design_conclusion] || CONCLUSION.pending).tone}>
                              Design: {(CONCLUSION[row.design_conclusion] || CONCLUSION.pending).label}
                            </Badge>
                            <Badge tone={(CONCLUSION[row.operating_conclusion] || CONCLUSION.pending).tone}>
                              Operating: {(CONCLUSION[row.operating_conclusion] || CONCLUSION.pending).label}
                            </Badge>
                          </span>
                        </div>

                        {row.evidence.length ? (
                          <ul className="mt-2 flex flex-wrap gap-1.5">
                            {row.evidence.map((e) => (
                              <li key={e.id}>
                                <button
                                  type="button"
                                  onClick={() => openEvidence(e)}
                                  className="flex items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2 py-1 text-2xs text-muted transition-colors duration-150 ease-out hover:border-line-strong hover:text-ink"
                                  title={`Open · v${e.pinned_version} · ${e.content_sha256.slice(0, 16)}…`}
                                >
                                  <FileTextIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
                                  {e.document_name}
                                </button>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <Label className="mt-2 block">No evidence attached</Label>
                        )}

                        {row.auditor_note ? (
                          <p className="mt-2 text-xs leading-snug text-muted">
                            <span className="text-faint">Auditor: </span>{row.auditor_note}
                          </p>
                        ) : null}
                        {row.management_response ? (
                          <p className="mt-1 text-xs leading-snug text-muted">
                            <span className="text-faint">Management: </span>{row.management_response}
                          </p>
                        ) : null}

                        <div className="mt-2.5 flex flex-wrap gap-1.5">
                          {["no_exceptions", "exceptions", "not_tested"].map((value) => (
                            <Button
                              key={value}
                              size="sm"
                              variant={row.operating_conclusion === value ? "primary" : "ghost"}
                              disabled={busy === `row-${row.id}`}
                              onClick={() => conclude(row, "operating_conclusion", value)}
                            >
                              {CONCLUSION[value].label}
                            </Button>
                          ))}
                          {canAssemble && row.operating_conclusion === "exceptions" && !row.risk ? (
                            <Button size="sm" variant="danger"
                                    onClick={() => act(`row-${row.id}`, async () => {
                                      await api.post(`/package-controls/${row.id}/promote/`);
                                      setRows(await fetchAll(`/package-controls/?package=${selectedId}`));
                                    }, "Raised in the risk register.")}>
                              Raise as a risk
                            </Button>
                          ) : null}
                          {row.risk ? <Badge tone="info">Tracked as a risk</Badge> : null}
                        </div>
                      </motion.li>
                    ))}
                  </AnimatePresence>
                </ul>
              )}
              <p className="border-t border-line px-5 py-3 text-xs text-muted">
                Conclusions are recorded by the auditor the package was issued to, and nobody at
                this organisation can edit them. The management response is yours to write.
              </p>
            </Panel>
          </>
        )}
      </div>
    </div>
    <DocumentViewer open={!!viewing} {...(viewing || {})} onClose={() => setViewing(null)} />
    </PanelTransition>
  );
}

function IssueForm({ packageId, onDone, onError }) {
  const [open, setOpen] = useState(false);
  const [auditors, setAuditors] = useState([]);
  const [user, setUser] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    fetchAll("/users/")
      .then((all) => setAuditors(all.filter((u) => u.is_active && u.role_detail?.is_auditor)))
      .catch(() => setAuditors([]));
  }, [open]);

  if (!open) {
    return (
      <Button size="sm" onClick={() => setOpen(true)}
              icon={<UserPlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
        Issue
      </Button>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await api.post("/package-grants/", { package: packageId, user: Number(user) });
          setOpen(false);
          setUser("");
          await onDone();
        } catch (err) {
          onError(errorText(err, "Couldn't issue the package."));
        } finally {
          setBusy(false);
        }
      }}
    >
      <select className="input h-8 py-0 text-xs" required value={user}
              aria-label="Auditor to issue to"
              onChange={(e) => setUser(e.target.value)}>
        <option value="">Choose an auditor…</option>
        {auditors.map((u) => (
          <option key={u.id} value={u.id}>{u.full_name || u.username}</option>
        ))}
      </select>
      <Button size="sm" variant="primary" type="submit" disabled={busy || !user}>
        {busy ? "Issuing…" : "Issue"}
      </Button>
      <Button size="sm" variant="ghost" type="button" onClick={() => setOpen(false)}>
        <XIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
      </Button>
    </form>
  );
}
