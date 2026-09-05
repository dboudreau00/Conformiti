/**
 * Third-party risk: the vendor register, the assurance each vendor has given
 * us (SOC 2 reports, PCI AOCs, pen tests, questionnaires), and the shared
 * responsibility matrix — which of our controls the provider does, which we
 * do, which are split, with the statement for each side.
 *
 * The matrix is an in-browser grid over every control in scope. It can be
 * filled three ways: typing into the grid, being walked through the unstated
 * controls one at a time, or importing the vendor's own CSV/XLSX, which the
 * server reads with column and value recognition and reports back before
 * anything is written.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Building2Icon, DownloadIcon, FileUpIcon, SparklesIcon, XIcon } from "lucide-react";
import api, { downloadFile, fetchAll } from "../api/client.js";
import { Collapse, EASE, PanelTransition } from "../components/layout/PanelTransition.jsx";
import DocumentViewer from "../components/documents/DocumentViewer.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Meter } from "../components/ui/Meter.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Chip, SegmentedControl } from "../components/ui/SegmentedControl.jsx";
import { StatCard } from "../components/ui/StatCard.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";

const TIERS = [["critical", "Critical"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]];
const TIER_TONE = { critical: "danger", high: "warning", medium: "info", low: "muted" };
const STATUSES = [["prospective", "Prospective"], ["active", "Active"], ["offboarding", "Offboarding"], ["offboarded", "Offboarded"]];
const CADENCES = [["quarterly", "Quarterly"], ["semiannual", "Every 6 months"], ["annual", "Annual"], ["biennial", "Every 2 years"]];
const POSTURE = {
  current: { label: "Current", tone: "success" },
  partial: { label: "Partial", tone: "warning" },
  expired: { label: "Expired", tone: "danger" },
  unsatisfactory: { label: "Unsatisfactory", tone: "danger" },
  none: { label: "No assurance", tone: "muted" },
};
const RATING = {
  critical: { label: "Critical", tone: "danger" },
  high: { label: "High", tone: "warning" },
  moderate: { label: "Moderate", tone: "info" },
  low: { label: "Low", tone: "success" },
};
const KINDS = [
  ["soc2_type2", "SOC 2 Type II"], ["soc2_type1", "SOC 2 Type I"], ["iso27001", "ISO 27001 certificate"],
  ["pci_aoc", "PCI DSS Attestation of Compliance"], ["pentest", "Penetration test"],
  ["questionnaire", "Security questionnaire"], ["dpa", "Data processing agreement"],
  ["contract", "Contract / MSA"], ["resp_matrix", "Their shared responsibility matrix"],
  ["bridge_letter", "Bridge letter"], ["other", "Other"],
];
const KIND_LABEL = Object.fromEntries(KINDS);
const RESULTS = [["pending", "Pending review"], ["satisfactory", "Satisfactory"], ["exceptions", "Exceptions noted"], ["unsatisfactory", "Unsatisfactory"]];
const RESULT_TONE = { pending: "faint", satisfactory: "success", exceptions: "warning", unsatisfactory: "danger" };
const RESP = [["provider", "Provider"], ["customer", "Us"], ["shared", "Shared"], ["not_applicable", "N/A"]];
const RESP_LABEL = { provider: "Provider", customer: "Us", shared: "Shared", not_applicable: "N/A" };
const RESP_TONE = { provider: "info", customer: "accent", shared: "warning", not_applicable: "muted" };
const ANSWERS = [["yes", "Yes"], ["partial", "Partial"], ["no", "No"], ["n/a", "N/A"]];
const FRAMEWORK_LABEL = { soc2: "SOC 2", iso27001: "ISO 27001", pci_dss_v4: "PCI DSS" };
const TABS = [
  { id: "overview", label: "Overview" },
  { id: "assessments", label: "Assurance" },
  { id: "questionnaire", label: "Questionnaire" },
  { id: "matrix", label: "Responsibility matrix" },
];
const EMPTY_VENDOR = {
  name: "", category: "", website: "", contact_name: "", contact_email: "", tier: "medium", status: "active",
  data_handled: "", services: "", owner: "", review_cadence: "annual", notes: "",
};

const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric" });
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : DATE_FMT.format(d);
}
const slug = (s) => String(s || "vendor").replace(/[^\w-]+/g, "-").toLowerCase();
function hostOf(url) {
  try { return new URL(url).host; } catch { return url; }
}

function Notice({ msg, onClose }) {
  return (
    <AnimatePresence initial={false}>
      {msg ? (
        <motion.div key={`${msg.ok}-${msg.text}`} initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18, ease: EASE }}>
          <div className={cn("notice flex items-start justify-between gap-3", msg.ok ? "notice-ok" : "notice-err")} role={msg.ok ? "status" : "alert"}>
            <span>{msg.text}</span>
            <button type="button" aria-label="Dismiss" onClick={onClose} className="shrink-0 opacity-70 transition-opacity hover:opacity-100">
              <XIcon className="h-3.5 w-3.5" />
            </button>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function Field({ id, label, children, className }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="field-label">{label}</label>
      {children}
    </div>
  );
}

// --- Register form --------------------------------------------------------------------

function VendorForm({ initial, users, busy, onSubmit, onCancel, submitLabel = "Save" }) {
  const [v, setV] = useState(() => ({ ...EMPTY_VENDOR, ...initial, owner: initial?.owner ?? "" }));
  const set = (k) => (e) => setV((cur) => ({ ...cur, [k]: e.target.value }));
  const id = (k) => `vendor-${k}`;
  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        // An empty website is sent as empty, so a bad address can be cleared.
        onSubmit({ ...v, website: (v.website || "").trim(), owner: v.owner ? Number(v.owner) : null });
      }}
    >
      <Field id={id("name")} label="Vendor name" className="sm:col-span-2">
        <input id={id("name")} className="input input-sm" required value={v.name} onChange={set("name")} placeholder="Amazon Web Services" />
      </Field>
      <Field id={id("category")} label="What they do for us">
        <input id={id("category")} className="input input-sm" value={v.category} onChange={set("category")} placeholder="Cloud hosting" />
      </Field>
      <Field id={id("website")} label="Website (https)">
        <input id={id("website")} className="input input-sm" value={v.website} onChange={set("website")} placeholder="https://" />
      </Field>
      <Field id={id("tier")} label="Criticality tier">
        <select id={id("tier")} className="input input-sm" value={v.tier} onChange={set("tier")}>
          {TIERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </Field>
      <Field id={id("status")} label="Status">
        <select id={id("status")} className="input input-sm" value={v.status} onChange={set("status")}>
          {STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </Field>
      <Field id={id("data")} label="Data of ours they touch" className="sm:col-span-2">
        <input id={id("data")} className="input input-sm" value={v.data_handled} onChange={set("data_handled")} placeholder="customer PII, cardholder data" />
      </Field>
      <Field id={id("services")} label="Services in scope" className="sm:col-span-2">
        <input id={id("services")} className="input input-sm" value={v.services} onChange={set("services")} placeholder="EC2, RDS, S3 in eu-west-1" />
      </Field>
      <Field id={id("contact")} label="Contact name">
        <input id={id("contact")} className="input input-sm" value={v.contact_name} onChange={set("contact_name")} />
      </Field>
      <Field id={id("email")} label="Contact email">
        <input id={id("email")} type="email" className="input input-sm" value={v.contact_email} onChange={set("contact_email")} />
      </Field>
      <Field id={id("owner")} label="Relationship owner">
        <select id={id("owner")} className="input input-sm" value={v.owner} onChange={set("owner")}>
          <option value="">Unassigned</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
        </select>
      </Field>
      <Field id={id("cadence")} label="Review cadence">
        <select id={id("cadence")} className="input input-sm" value={v.review_cadence} onChange={set("review_cadence")}>
          {CADENCES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </Field>
      <Field id={id("notes")} label="Notes" className="sm:col-span-2">
        <textarea id={id("notes")} className="input input-sm min-h-[64px]" value={v.notes} onChange={set("notes")} />
      </Field>
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" variant="primary" disabled={busy || !v.name.trim()}>{busy ? "Saving…" : submitLabel}</Button>
        {onCancel ? <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button> : null}
      </div>
    </form>
  );
}

// --- Overview -------------------------------------------------------------------------

function OverviewTab({ vendor, users, canManage, busy, onSave, onReviewed }) {
  const [editing, setEditing] = useState(false);
  const a = vendor.assurance || {};
  const posture = POSTURE[a.posture] || POSTURE.none;
  const rating = RATING[vendor.risk_rating] || RATING.moderate;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Risk rating" value={rating.label} tone={rating.tone} detail={`${vendor.tier_display} tier × assurance held`} />
        <StatCard label="Assurance" value={posture.label} tone={posture.tone}
                  detail={`${a.current || 0} current · ${a.expired || 0} expired${a.unsatisfactory ? ` · ${a.unsatisfactory} unsatisfactory` : ""}`} />
        <StatCard label="Next review" value={fmtDate(vendor.next_review_date)} tone={vendor.is_review_overdue ? "danger" : "muted"}
                  detail={vendor.last_reviewed ? `Last reviewed ${fmtDate(vendor.last_reviewed)}` : "Never reviewed"} />
        <StatCard label="Controls stated" value={vendor.control_count} detail={`${vendor.open_risk_count} open risk(s)`} tone={vendor.control_count ? "accent" : "warning"} />
      </div>

      <Panel className="p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <Label>Register entry</Label>
          {canManage && !editing ? (
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={onReviewed} disabled={busy}>Mark reviewed</Button>
              <Button size="sm" onClick={() => setEditing(true)}>Edit</Button>
            </div>
          ) : null}
        </div>
        {editing ? (
          <VendorForm initial={vendor} users={users} busy={busy} submitLabel="Save changes"
                      onSubmit={async (body) => { if (await onSave(body)) setEditing(false); }}
                      onCancel={() => setEditing(false)} />
        ) : (
          <dl className="grid gap-x-6 gap-y-3 text-[13px] sm:grid-cols-2">
            {[
              ["Category", vendor.category], ["Website", vendor.website], ["Data handled", vendor.data_handled],
              ["Services", vendor.services], ["Contact", [vendor.contact_name, vendor.contact_email].filter(Boolean).join(" · ")],
              ["Relationship owner", vendor.owner_name], ["Review cadence", CADENCES.find(([k]) => k === vendor.review_cadence)?.[1]],
              ["Onboarded", fmtDate(vendor.created_at)],
            ].map(([k, v]) => (
              <div key={k}>
                <Label as="dt">{k}</Label>
                <dd className={cn("mt-0.5 break-words", v ? "text-ink" : "text-faint")}>{v || "—"}</dd>
              </div>
            ))}
            {vendor.notes ? (
              <div className="sm:col-span-2">
                <Label as="dt">Notes</Label>
                <dd className="mt-0.5 whitespace-pre-line text-muted">{vendor.notes}</dd>
              </div>
            ) : null}
          </dl>
        )}
      </Panel>
    </div>
  );
}

// --- Assurance on file ------------------------------------------------------------------

const EMPTY_ASSESSMENT = { kind: "soc2_type2", title: "", issued_at: "", expires_at: "", period_start: "", period_end: "", result: "pending", document: "", findings: "" };

function AssessmentsTab({ vendor, docs, canManage, busy, onFile, onRemove, onOpen }) {
  const [adding, setAdding] = useState(false);
  const [a, setA] = useState(EMPTY_ASSESSMENT);
  const set = (k) => (e) => setA((cur) => ({ ...cur, [k]: e.target.value }));
  const rows = (vendor.assessments || []).filter((x) => x.kind !== "questionnaire");

  return (
    <div className="space-y-4">
      <Panel className="overflow-hidden">
        <PanelHeader title="Reports and attestations on file" meta={`${rows.length} filed`}>
          {canManage ? (
            <Button size="sm" variant={adding ? "secondary" : "primary"} aria-expanded={adding} onClick={() => setAdding((x) => !x)}
                    icon={<FileUpIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
              File a report
            </Button>
          ) : null}
        </PanelHeader>
        <AnimatePresence initial={false}>
          {adding ? (
            <Collapse key="file" open>
              <form
                className="grid gap-3 border-b border-line bg-surface-2 px-5 py-4 sm:grid-cols-2"
                onSubmit={async (e) => {
                  e.preventDefault();
                  const body = { ...a, vendor: vendor.id, document: a.document ? Number(a.document) : null };
                  for (const k of ["issued_at", "expires_at", "period_start", "period_end"]) if (!body[k]) body[k] = null;
                  if (await onFile(body)) { setA(EMPTY_ASSESSMENT); setAdding(false); }
                }}
              >
                <Field id="as-kind" label="Kind">
                  <select id="as-kind" className="input input-sm" value={a.kind} onChange={set("kind")}>
                    {KINDS.filter(([k]) => k !== "questionnaire").map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </Field>
                <Field id="as-title" label="Title">
                  <input id="as-title" className="input input-sm" value={a.title} onChange={set("title")} placeholder="SOC 2 Type II, FY2026" />
                </Field>
                <Field id="as-issued" label="Issued">
                  <input id="as-issued" type="date" className="input input-sm" value={a.issued_at} onChange={set("issued_at")} />
                </Field>
                <Field id="as-expires" label="Expires / next due">
                  <input id="as-expires" type="date" className="input input-sm" value={a.expires_at} onChange={set("expires_at")} />
                </Field>
                <Field id="as-pstart" label="Period start">
                  <input id="as-pstart" type="date" className="input input-sm" value={a.period_start} onChange={set("period_start")} />
                </Field>
                <Field id="as-pend" label="Period end">
                  <input id="as-pend" type="date" className="input input-sm" value={a.period_end} onChange={set("period_end")} />
                </Field>
                <Field id="as-result" label="Our conclusion">
                  <select id="as-result" className="input input-sm" value={a.result} onChange={set("result")}>
                    {RESULTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </Field>
                <Field id="as-doc" label="Copy on file (document)">
                  <select id="as-doc" className="input input-sm" value={a.document} onChange={set("document")}>
                    <option value="">{docs ? "None — not uploaded yet" : "Loading documents…"}</option>
                    {(docs || []).map((d) => <option key={d.id} value={d.id}>{d.path} / {d.name}</option>)}
                  </select>
                </Field>
                <Field id="as-findings" label="Findings / exceptions" className="sm:col-span-2">
                  <textarea id="as-findings" className="input input-sm min-h-[56px]" value={a.findings} onChange={set("findings")} />
                </Field>
                <div className="flex gap-2 sm:col-span-2">
                  <Button type="submit" size="sm" variant="primary" disabled={busy}>{busy ? "Filing…" : "File"}</Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
                </div>
                <p className="text-2xs text-faint sm:col-span-2">
                  Upload the AOC or matrix into a folder on the Documents page first; then pick it here so the copy is filed against the vendor.
                </p>
              </form>
            </Collapse>
          ) : null}
        </AnimatePresence>
        {rows.length === 0 ? (
          <Empty title="Nothing on file">
            {canManage ? "File their SOC 2 report, PCI AOC, pen test or a copy of their responsibility matrix." : "No assurance has been filed for this vendor."}
          </Empty>
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 px-5 py-3">
                <div className="min-w-0">
                  <p className="text-[13px] font-medium text-ink">
                    {KIND_LABEL[r.kind] || r.kind_display}{r.title ? ` — ${r.title}` : ""}
                  </p>
                  <Label className="mt-0.5 block">
                    {r.period_start || r.period_end ? `Period ${fmtDate(r.period_start)} → ${fmtDate(r.period_end)} · ` : ""}
                    {r.issued_at ? `Issued ${fmtDate(r.issued_at)} · ` : ""}
                    {r.expires_at ? `${r.is_expired ? "Expired" : "Expires"} ${fmtDate(r.expires_at)}` : "No expiry"}
                    {r.reviewed_by_name ? ` · reviewed by ${r.reviewed_by_name}` : ""}
                  </Label>
                  {r.findings ? <p className="mt-1 text-xs text-muted">{r.findings}</p> : null}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={RESULT_TONE[r.result] || "muted"} dot>{r.result_display}</Badge>
                  {r.is_expired ? <Badge tone="danger" mono>expired</Badge> : null}
                  {r.document ? (
                    <Button size="sm" variant="ghost" onClick={() => onOpen(r)}>Open {r.document_name}</Button>
                  ) : r.document_hidden ? (
                    <Badge tone="muted" mono title="A copy is filed in a folder you cannot see">copy filed · not visible to you</Badge>
                  ) : <Badge tone="faint" mono>no copy filed</Badge>}
                  {canManage ? <Button size="sm" variant="ghost" onClick={() => onRemove(r)} disabled={busy} aria-label={`Remove ${KIND_LABEL[r.kind] || r.kind}`}>Remove</Button> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

// --- Questionnaire ----------------------------------------------------------------------

const INVITE_TONE = { open: "info", submitted: "success", expired: "warning", revoked: "muted" };
const OUTCOMES = [["satisfactory", "Satisfactory"], ["exceptions", "Exceptions noted"], ["unsatisfactory", "Unsatisfactory"]];

/** Emailing the questionnaire to the vendor: a time-boxed link they answer
 * themselves, the links sent so far, and the link shown exactly once. */
function SendToVendor({ vendor, busy, act, refresh }) {
  const invites = vendor.questionnaire_invites || [];
  const [sending, setSending] = useState(false);
  const [form, setForm] = useState({ email: vendor.contact_email || "", days: 14, message: "" });
  const [sent, setSent] = useState(null);
  const openCount = invites.filter((i) => i.status === "open").length;

  const send = (e) => {
    e.preventDefault();
    return act(async () => {
      const { data } = await api.post(`/vendors/${vendor.id}/questionnaire/send/`, {
        email: form.email.trim(), days: Number(form.days) || 14, message: form.message,
      });
      setSent(data);
      setSending(false);
      await refresh();
    }, "Questionnaire sent to the vendor.");
  };
  const revoke = (inv) => act(async () => { await api.post(`/questionnaire-invites/${inv.id}/revoke/`); await refresh(); }, "Link withdrawn.");

  return (
    <Panel className="overflow-hidden" aria-label="Send to the vendor">
      <PanelHeader title="Sent to the vendor" meta={openCount ? `${openCount} open link${openCount === 1 ? "" : "s"}` : "No open link"}>
        <Button size="sm" variant={sending ? "secondary" : "primary"} aria-expanded={sending} disabled={busy} onClick={() => { setSending((x) => !x); setSent(null); }}>
          Send to the vendor
        </Button>
      </PanelHeader>
      {sending ? (
        <form onSubmit={send} className="grid gap-3 border-b border-line bg-surface-2 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_120px]">
          <Field id="qsend-email" label="Their contact's email">
            <input id="qsend-email" type="email" className="input" required value={form.email} placeholder="security@vendor.example"
                   onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
          <Field id="qsend-days" label="Link valid for (days)">
            <input id="qsend-days" type="number" min="1" max="90" className="input" value={form.days}
                   onChange={(e) => setForm({ ...form, days: e.target.value })} />
          </Field>
          <Field id="qsend-message" label="A note to them (optional)" className="sm:col-span-2">
            <textarea id="qsend-message" className="input min-h-[72px]" value={form.message} placeholder="We are preparing for our SOC 2 audit and need this back before the 20th."
                      onChange={(e) => setForm({ ...form, message: e.target.value })} />
          </Field>
          <div className="flex items-center gap-2 sm:col-span-2">
            <Button type="submit" size="sm" variant="primary" disabled={busy || !form.email.trim()}>Send</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setSending(false)}>Cancel</Button>
            <Label>A new link supersedes any open one.</Label>
          </div>
        </form>
      ) : null}
      {sent ? (
        <div className="notice notice-ok m-4" role="status">
          <span className="block font-medium">{sent.email_sent ? `Emailed to ${sent.sent_to}.` : "The email could not be sent — paste the link into your own message."}</span>
          <span className="mt-1 block text-xs">The link, shown once:</span>
          <code id="questionnaire-link" className="mt-1 block select-all break-all font-mono text-xs text-ink">{sent.link}</code>
        </div>
      ) : null}
      {invites.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-faint">
                <th className="px-5 py-2 font-normal" scope="col">Sent to</th>
                <th className="py-2 pr-3 font-normal" scope="col">Sent</th>
                <th className="py-2 pr-3 font-normal" scope="col">Valid until</th>
                <th className="py-2 pr-3 font-normal" scope="col">Status</th>
                <th className="py-2 pr-3 font-normal" scope="col">Answered by</th>
                <th className="py-2 pr-5 font-normal" scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {invites.map((inv) => (
                <tr key={inv.id} className="align-top">
                  <td className="px-5 py-2 text-ink">{inv.sent_to}<span className="block text-faint">by {inv.sent_by_name}{inv.email_sent ? "" : " · email not sent"}</span></td>
                  <td className="py-2 pr-3 text-muted">{fmtDate(inv.sent_at)}</td>
                  <td className="py-2 pr-3 text-muted">{fmtDate(inv.expires_at)}</td>
                  <td className="py-2 pr-3">
                    <Badge tone={INVITE_TONE[inv.status] || "muted"} dot>{inv.status}</Badge>
                    {inv.status === "open" && inv.opened_at ? <span className="block text-faint">opened {fmtDate(inv.opened_at)}{inv.saved_at ? ", draft saved" : ""}</span> : null}
                  </td>
                  <td className="py-2 pr-3 text-muted">{inv.respondent_name ? `${inv.respondent_name}${inv.respondent_title ? ` (${inv.respondent_title})` : ""} · ${fmtDate(inv.submitted_at)}` : "—"}</td>
                  <td className="py-2 pr-5 text-right">
                    {inv.status === "open" ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => revoke(inv)}>Revoke</Button> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-5 py-3 text-xs text-muted">Nothing sent yet. The vendor gets an email with a personal link, answers in their browser, and the result lands here as a pending assessment for you to review.</p>
      )}
    </Panel>
  );
}

function QuestionnaireTab({ vendor, canManage, busy, onSubmit, act, refresh }) {
  const latest = (vendor.assessments || []).filter((x) => x.kind === "questionnaire").sort((x, y) => (x.created_at < y.created_at ? 1 : -1))[0];
  const [answers, setAnswers] = useState(() => latest?.answers || {});
  // A submission arriving from the vendor replaces what is on screen.
  useEffect(() => { setAnswers(latest?.answers || {}); }, [latest?.id]);
  const returned = latest && latest.result === "pending"
    ? (vendor.questionnaire_invites || []).find((i) => i.assessment === latest.id) : null;
  const questions = vendor.questionnaire || [];
  const areas = useMemo(() => {
    const out = [];
    for (const q of questions) {
      let a = out.find((x) => x.area === q.area);
      if (!a) { a = { area: q.area, items: [] }; out.push(a); }
      a.items.push(q);
    }
    return out;
  }, [questions]);
  const answered = questions.filter((q) => answers[q.id]?.answer).length;
  const setAnswer = (id, patch) => setAnswers((cur) => ({ ...cur, [id]: { ...(cur[id] || {}), ...patch } }));
  const suggested = Object.values(answers).some((x) => x?.answer === "no") ? "exceptions" : "satisfactory";

  const lastMeta = !latest ? "Not yet completed"
    : returned ? `Returned by ${returned.respondent_name || returned.sent_to} on ${fmtDate(latest.created_at)} · pending review`
    : `Last submitted ${fmtDate(latest.created_at)} by ${latest.reviewed_by_name || "the vendor"}`;

  return (
    <div className="flex flex-col gap-4">
    {canManage ? <SendToVendor vendor={vendor} busy={busy} act={act} refresh={refresh} /> : null}
    {returned ? (
      <div className="notice notice-warn flex flex-wrap items-center justify-between gap-3" role="status">
        <span>
          <span className="font-medium">Returned by {returned.respondent_name || returned.sent_to}{returned.respondent_title ? ` (${returned.respondent_title})` : ""} on {fmtDate(latest.created_at)}.</span>{" "}
          Review the answers below and record the outcome.
        </span>
        {canManage ? (
          <span className="flex flex-wrap gap-2">
            {OUTCOMES.map(([k, l]) => (
              <Button key={k} size="sm" variant={k === "unsatisfactory" ? "danger" : k === "satisfactory" ? "primary" : "secondary"} disabled={busy}
                      onClick={() => act(async () => { await api.patch(`/vendor-assessments/${latest.id}/`, { result: k }); await refresh(); }, `Outcome recorded: ${l.toLowerCase()}.`)}>
                {l}
              </Button>
            ))}
          </span>
        ) : null}
      </div>
    ) : null}
    <Panel className="overflow-hidden">
      <PanelHeader title="Security questionnaire" meta={lastMeta}>
        <div className="flex items-center gap-3">
          <Meter value={answered} total={questions.length || 1} className="w-32" ariaLabel="Questions answered" />
          <Label>{answered}/{questions.length}</Label>
        </div>
      </PanelHeader>
      <div className="divide-y divide-line">
        {areas.map((a) => (
          <fieldset key={a.area} className="px-5 py-4">
            <legend className="mb-2 font-mono text-2xs uppercase tracking-label text-faint">{a.area}</legend>
            <ul className="space-y-3">
              {a.items.map((q) => (
                <li key={q.id} className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
                  <p className="text-[13px] text-ink">{q.text}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {ANSWERS.map(([k, l]) => (
                      <Chip key={k} active={answers[q.id]?.answer === k} onClick={() => canManage && setAnswer(q.id, { answer: k })}>{l}</Chip>
                    ))}
                    <input className="input input-sm w-48" placeholder="Note" aria-label={`Note for: ${q.text}`} value={answers[q.id]?.note || ""}
                           disabled={!canManage} onChange={(e) => setAnswer(q.id, { note: e.target.value })} />
                  </div>
                </li>
              ))}
            </ul>
          </fieldset>
        ))}
      </div>
      {canManage ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface-2 px-5 py-3">
          <Button size="sm" variant="primary" disabled={busy || answered === 0}
                  onClick={() => onSubmit({ vendor: vendor.id, kind: "questionnaire", title: `Questionnaire ${new Date().toISOString().slice(0, 10)}`, result: suggested, answers })}>
            {busy ? "Saving…" : "Save questionnaire"}
          </Button>
          <Label>Saved as a dated assessment; a "No" marks it as exceptions noted.</Label>
        </div>
      ) : null}
    </Panel>
    </div>
  );
}

// --- Shared responsibility matrix --------------------------------------------------------

function RespPicker({ value, onChange, disabled, compact = false, label = "Responsibility" }) {
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
      {RESP.map(([k, l]) => (
        <button key={k} type="button" disabled={disabled} aria-pressed={value === k} onClick={() => onChange(value === k ? null : k)}
                className={cn("rounded-md border px-2 py-0.5 text-2xs font-medium transition-colors duration-150",
                  compact ? "" : "px-3 py-1.5 text-xs",
                  value === k ? "border-accent bg-accent/10 text-accent" : "border-line text-muted hover:border-line-strong hover:text-ink",
                  disabled && "opacity-60")}>
          {l}
        </button>
      ))}
    </div>
  );
}

function PromptMode({ rows, vendorName, busy, onSave, onDone }) {
  // `rows` is the live list of unstated controls: a saved control leaves it,
  // so the next one slides into the same index. Only a skip advances.
  const [i, setI] = useState(0);
  const [draft, setDraft] = useState({ responsibility: null, provider_statement: "", customer_statement: "" });
  // Skipped items come round again: when the index runs past the end of a
  // list that still has entries, start over rather than declare it done.
  const index = rows.length && i >= rows.length ? 0 : i;
  const row = rows[index];
  useEffect(() => { if (rows.length && i >= rows.length) setI(0); }, [i, rows.length]);
  useEffect(() => { setDraft({ responsibility: null, provider_statement: "", customer_statement: "" }); }, [row?.control]);
  if (!row) {
    return (
      <div className="rounded-xl border border-line bg-surface-2 p-6 text-center">
        <p className="text-sm font-medium text-ink">Every control in this view has a stated responsibility.</p>
        <Button size="sm" className="mt-3" onClick={onDone}>Back to the grid</Button>
      </div>
    );
  }
  return (
    <motion.div key={row.control} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.18, ease: EASE }}
                className="rounded-xl border border-accent/40 bg-accent/[0.04] p-5" aria-live="polite"
                role="region" aria-label="Responsibility prompt">
      <div className="flex items-center justify-between gap-3">
        <Label>Control {index + 1} of {rows.length} without a statement</Label>
        <Button size="sm" variant="ghost" onClick={onDone}>Exit</Button>
      </div>
      <h3 className="mt-2 text-[15px] font-semibold text-ink">
        <span className="font-mono text-sm text-muted">{row.control_id}</span> {row.title}
      </h3>
      <Label className="mt-0.5 block">{FRAMEWORK_LABEL[row.framework] || row.framework} · {row.category}</Label>
      <p className="mt-3 text-[13px] text-muted">Who does this control for the services {vendorName} provides?</p>
      <div className="mt-2"><RespPicker value={draft.responsibility} onChange={(v) => setDraft((d) => ({ ...d, responsibility: v }))} /></div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field id="pm-provider" label={`What ${vendorName} does`}>
          <textarea id="pm-provider" className="input input-sm min-h-[64px]" value={draft.provider_statement}
                    disabled={draft.responsibility === "customer" || draft.responsibility === "not_applicable"}
                    onChange={(e) => setDraft((d) => ({ ...d, provider_statement: e.target.value }))} />
        </Field>
        <Field id="pm-customer" label="What we do">
          <textarea id="pm-customer" className="input input-sm min-h-[64px]" value={draft.customer_statement}
                    disabled={draft.responsibility === "provider" || draft.responsibility === "not_applicable"}
                    onChange={(e) => setDraft((d) => ({ ...d, customer_statement: e.target.value }))} />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={busy || !draft.responsibility}
                onClick={() => onSave({ control: row.control, ...draft })}>
          {busy ? "Saving…" : "Save and next"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setI((x) => x + 1)} disabled={busy}>Skip</Button>
      </div>
    </motion.div>
  );
}

function ImportWizard({ vendor, framework, frameworks = [], controls, busy, onConfirm, onCancel, setMsg }) {
  const fileRef = useRef(null);
  const [parsing, setParsing] = useState(false);
  const [review, setReview] = useState(null);
  // A bare "6.1" is a PCI requirement, an ISO clause and a SOC 2 point of
  // focus; the file is about one of them and only the person knows which.
  const [fw, setFw] = useState(framework || (frameworks.length === 1 ? frameworks[0] : ""));

  async function parse(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !fw) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("framework", fw);
    setParsing(true);
    try {
      const { data } = await api.post(`/vendors/${vendor.id}/matrix/parse/`, fd);
      setReview({ ...data, file_name: file.name, rows: data.rows.map((r, i) => ({ ...r, key: i, include: r.matched && !!r.responsibility })) });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't read that file.") });
    } finally {
      setParsing(false);
    }
  }
  const patch = (key, p) => setReview((cur) => ({ ...cur, rows: cur.rows.map((r) => (r.key === key ? { ...r, ...p } : r)) }));
  const ready = review ? review.rows.filter((r) => r.include && r.control_id && r.responsibility) : [];

  return (
    <div className="rounded-xl border border-line bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-ink">Import {vendor.name}'s responsibility matrix</p>
          <Label className="block">CSV or XLSX, in whatever layout they sent. Columns and values are recognised, then you confirm before anything is written.</Label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="import-framework" className="sr-only">Framework in the file</label>
          <select id="import-framework" className="input input-sm w-44" value={fw} onChange={(e) => { setFw(e.target.value); setReview(null); }} disabled={parsing || busy}>
            <option value="">Framework in the file…</option>
            {frameworks.map((k) => <option key={k} value={k}>{FRAMEWORK_LABEL[k] || k}</option>)}
          </select>
          <input ref={fileRef} type="file" accept=".csv,.xlsx" className="hidden" onChange={parse} aria-label="Matrix file" />
          <Button size="sm" variant="primary" onClick={() => fileRef.current?.click()} disabled={parsing || busy || !fw}
                  icon={<FileUpIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
            {parsing ? "Reading…" : review ? "Choose another file" : "Choose file"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
        </div>
      </div>

      {review ? (
        <div className="mt-4 space-y-3">
          {review.summary?.error ? <p className="notice notice-err" role="alert">{review.summary.error}</p> : null}
          {review.summary?.truncated ? (
            <p className="notice notice-warn" role="status">
              Only the first {review.summary.row_limit} rows were read. Split the file and import the rest separately.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-1.5" aria-label="How the columns were read">
            {review.columns.map((c) => (
              <Badge key={c.index} tone={c.role ? (c.role === "control" ? "accent" : "info") : "faint"} title={c.role ? `Read as ${c.role.replace("_", " ")} (${c.confidence}%)` : "Ignored"}>
                {c.column} → {c.role ? c.role.replace("_", " ") : "ignored"}
              </Badge>
            ))}
          </div>
          {!review.summary?.error ? (
            <>
              <div className="flex flex-wrap gap-3">
                <Label>{review.summary.total} rows</Label>
                <Label>{review.summary.matched} matched a control</Label>
                <Label className={review.summary.unmatched ? "text-warning" : ""}>{review.summary.unmatched} unmatched</Label>
                <Label className={review.summary.unrecognised_responsibility ? "text-warning" : ""}>{review.summary.unrecognised_responsibility} without a recognised responsibility</Label>
              </div>
              <div className="max-h-[420px] overflow-auto rounded-lg border border-line bg-surface">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-surface-2">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-normal text-faint" scope="col">Use</th>
                      <th className="px-2 py-1.5 text-left font-normal text-faint" scope="col">Their ref</th>
                      <th className="px-2 py-1.5 text-left font-normal text-faint" scope="col">Control</th>
                      <th className="px-2 py-1.5 text-left font-normal text-faint" scope="col">Responsibility</th>
                      <th className="px-2 py-1.5 text-left font-normal text-faint" scope="col">Provider statement</th>
                      <th className="px-2 py-1.5 text-left font-normal text-faint" scope="col">Customer statement</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {review.rows.map((r) => (
                      <tr key={r.key} className={cn(!r.matched && "bg-warning/[0.06]")}>
                        <td className="px-2 py-1.5"><input type="checkbox" checked={r.include} aria-label={`Import line ${r.line}`} onChange={(e) => patch(r.key, { include: e.target.checked })} /></td>
                        <td className="px-2 py-1.5 font-mono text-muted">{r.raw_ref}</td>
                        <td className="px-2 py-1.5">
                          <select className="input input-sm" aria-label={`Control for line ${r.line}`} value={r.control_id || ""}
                                  onChange={(e) => patch(r.key, { control_id: e.target.value ? Number(e.target.value) : null, matched: !!e.target.value, include: !!e.target.value })}>
                            <option value="">{r.matched ? "" : "Not matched — choose"}</option>
                            {controls.filter((c) => !fw || c.framework === fw).map((c) => <option key={c.id} value={c.id}>{c.label} — {c.title}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <select className={cn("input input-sm", !r.responsibility && "border-warning")} aria-label={`Responsibility for line ${r.line}`} value={r.responsibility || ""}
                                  onChange={(e) => patch(r.key, { responsibility: e.target.value || null, include: !!e.target.value && !!r.control_id })}>
                            <option value="">Not recognised — choose</option>
                            {RESP.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5"><input className="input input-sm" aria-label={`Provider statement for line ${r.line}`} value={r.provider_statement} onChange={(e) => patch(r.key, { provider_statement: e.target.value })} /></td>
                        <td className="px-2 py-1.5"><input className="input input-sm" aria-label={`Customer statement for line ${r.line}`} value={r.customer_statement} onChange={(e) => patch(r.key, { customer_statement: e.target.value })} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center gap-3">
                <Button size="sm" variant="primary" disabled={busy || ready.length === 0}
                        onClick={() => onConfirm(
                          ready.map((r) => ({ control: r.control_id, responsibility: r.responsibility, provider_statement: r.provider_statement, customer_statement: r.customer_statement })),
                          { layout: review.columns.map((c) => ({ name: c.column, role: c.role, index: c.index })), layout_name: review.file_name || "", framework: fw },
                        )}>
                  {busy ? "Importing…" : `Import ${ready.length} row(s)`}
                </Button>
                <Label>Rows already stated for this vendor are replaced; everything else is left alone. Their column layout is remembered, so the matrix can go back to them the same way.</Label>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function MatrixTab({ vendor, canManage, intent, onIntentDone, setMsg, onChanged }) {
  const [data, setData] = useState(null);
  const [fw, setFw] = useState("");
  const [q, setQ] = useState("");
  const [onlyUnstated, setOnlyUnstated] = useState(false);
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState(null); // "prompt" | "import"

  async function load() {
    try {
      const { data: d } = await api.get(`/vendors/${vendor.id}/matrix/`);
      setData(d);
    } catch (e) {
      setData({ rows: [], summary: { controls: 0, stated: 0, unstated: 0 } });
      setMsg({ ok: false, text: errorText(e, "Couldn't load the responsibility matrix.") });
    }
  }
  useEffect(() => { setEdits({}); load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, [vendor.id]);
  useEffect(() => { if (intent) { setMode(intent); onIntentDone(); } }, [intent, onIntentDone]);

  const frameworks = useMemo(() => {
    const seen = [];
    for (const r of data?.rows || []) if (!seen.includes(r.framework)) seen.push(r.framework);
    return seen;
  }, [data]);
  const controls = useMemo(() => (data?.rows || []).map((r) => ({ id: r.control, label: r.control_id, title: r.title, framework: r.framework })), [data]);
  const merged = useMemo(() => (data?.rows || []).map((r) => ({ ...r, ...(edits[r.control] || {}), dirty: !!edits[r.control] })), [data, edits]);
  const visible = useMemo(() => merged.filter((r) =>
    (!fw || r.framework === fw)
    && (!onlyUnstated || !r.responsibility)
    && (!q || `${r.control_id} ${r.title}`.toLowerCase().includes(q.toLowerCase()))
  ), [merged, fw, onlyUnstated, q]);
  const unstated = merged.filter((r) => !r.responsibility && (!fw || r.framework === fw));
  const dirtyCount = Object.keys(edits).length;
  // A statement with nothing to belong to: the server refuses it, so say so first.
  const orphaned = merged.filter((r) => r.dirty && !r.responsibility && ((r.provider_statement || "").trim() || (r.customer_statement || "").trim()));

  const edit = (control, patch) => setEdits((cur) => {
    const base = data.rows.find((r) => r.control === control) || {};
    return { ...cur, [control]: { responsibility: base.responsibility, provider_statement: base.provider_statement, customer_statement: base.customer_statement, ...(cur[control] || {}), ...patch } };
  });

  async function put(rows, source = "manual", okText, extra = {}) {
    setBusy(true);
    try {
      await api.put(`/vendors/${vendor.id}/matrix/`, { rows, source, ...extra });
      await load();
      onChanged();
      if (okText) setMsg({ ok: true, text: okText });
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e, "Couldn't save the matrix.") });
      return false;
    } finally {
      setBusy(false);
    }
  }
  const saveEdits = async () => {
    const rows = Object.entries(edits).map(([control, e]) => ({ control: Number(control), ...e }));
    if (await put(rows, "manual", `${rows.length} control(s) saved.`)) setEdits({});
  };

  if (!data) return <Panel><Loading /></Panel>;
  const s = data.summary;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Controls in scope" value={s.controls} />
        <StatCard label="Stated" value={s.stated} tone="success" detail={`${s.controls ? Math.round((s.stated / s.controls) * 100) : 0}% of the matrix`}>
          <Meter value={s.stated} total={s.controls || 1} tone="success" className="mt-2" ariaLabel="Matrix completion" />
        </StatCard>
        <StatCard label="Unstated" value={s.unstated} tone={s.unstated ? "warning" : "muted"} detail="Controls nobody has claimed yet" />
      </div>

      {mode === "prompt" ? (
        <PromptMode rows={unstated} vendorName={vendor.name} busy={busy}
                    onSave={(row) => put([row], "manual")} onDone={() => setMode(null)} />
      ) : mode === "import" ? (
        <ImportWizard vendor={vendor} framework={fw} frameworks={frameworks} controls={controls} busy={busy} setMsg={setMsg} onCancel={() => setMode(null)}
                      onConfirm={async (rows, extra) => { if (await put(rows, "import", `${rows.length} row(s) imported from ${vendor.name}'s matrix.`, extra)) setMode(null); }} />
      ) : null}

      <Panel className="overflow-hidden">
        <PanelHeader title="Shared responsibility matrix" meta={`${visible.length} of ${merged.length} controls`}>
          <div className="flex flex-wrap items-center gap-2">
            {canManage ? (
              <>
                <Button size="sm" variant={mode === "prompt" ? "secondary" : "primary"} disabled={busy || unstated.length === 0} onClick={() => setMode(mode === "prompt" ? null : "prompt")}
                        icon={<SparklesIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                  Walk me through {unstated.length ? `(${unstated.length})` : ""}
                </Button>
                <Button size="sm" variant={mode === "import" ? "secondary" : "ghost"} disabled={busy} onClick={() => setMode(mode === "import" ? null : "import")}
                        icon={<FileUpIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                  Import CSV/XLSX
                </Button>
              </>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => downloadFile(`/vendors/${vendor.id}/matrix/export/`, `responsibility-matrix-${slug(vendor.name)}.csv`)}
                    icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
              Export
            </Button>
            {vendor.matrix_layout ? (
              <Button size="sm" variant="ghost" title={`Columns from ${vendor.matrix_layout.file || "their last file"}`}
                      onClick={() => downloadFile(`/vendors/${vendor.id}/matrix/export/?layout=vendor`, `responsibility-matrix-${slug(vendor.name)}-their-layout.csv`)}
                      icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                Export in their layout
              </Button>
            ) : null}
          </div>
        </PanelHeader>
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-5 py-2.5">
          <Chip active={!fw} onClick={() => setFw("")}>All frameworks</Chip>
          {frameworks.map((k) => <Chip key={k} active={fw === k} onClick={() => setFw(k)}>{FRAMEWORK_LABEL[k] || k}</Chip>)}
          <Chip active={onlyUnstated} onClick={() => setOnlyUnstated((x) => !x)} tone="warning">Unstated only</Chip>
          <label htmlFor="matrix-search" className="sr-only">Search controls</label>
          <input id="matrix-search" className="input input-sm ml-auto w-56" placeholder="Search controls…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-xs">
            <thead className="bg-surface-2">
              <tr>
                <th className="px-4 py-2 text-left font-normal text-faint" scope="col">Control</th>
                <th className="px-2 py-2 text-left font-normal text-faint" scope="col">Responsibility</th>
                <th className="px-2 py-2 text-left font-normal text-faint" scope="col">{vendor.name} does</th>
                <th className="px-2 py-2 text-left font-normal text-faint" scope="col">We do</th>
                <th className="px-2 py-2 text-left font-normal text-faint" scope="col">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {visible.length === 0 ? (
                <tr><td colSpan={5}><Empty title="No controls match">Clear the filters, or pick another framework.</Empty></td></tr>
              ) : visible.map((r) => (
                <tr key={r.control} className={cn("align-top transition-colors duration-150 hover:bg-surface-2", r.dirty && "bg-accent/[0.04]")}>
                  <td className="w-[280px] px-4 py-2">
                    <span className="block font-mono text-[11px] text-muted">{FRAMEWORK_LABEL[r.framework] || r.framework} · {r.control_id}</span>
                    <span className="block text-[13px] text-ink">{r.title}</span>
                  </td>
                  <td className="w-[230px] px-2 py-2">
                    {canManage ? <RespPicker compact label={`Responsibility for ${r.control_id}`} value={r.responsibility} disabled={busy} onChange={(v) => edit(r.control, { responsibility: v })} />
                      : r.responsibility ? <Badge tone={RESP_TONE[r.responsibility]}>{RESP_LABEL[r.responsibility]}</Badge> : <span className="text-faint">—</span>}
                  </td>
                  <td className="px-2 py-2">
                    {canManage ? (
                      <textarea className="input input-sm min-h-[40px] w-full" rows={1} aria-label={`What ${vendor.name} does for ${r.control_id}`} value={r.provider_statement || ""} disabled={busy}
                                onChange={(e) => edit(r.control, { provider_statement: e.target.value })} />
                    ) : <span className="whitespace-pre-line text-muted">{r.provider_statement || "—"}</span>}
                  </td>
                  <td className="px-2 py-2">
                    {canManage ? (
                      <textarea className="input input-sm min-h-[40px] w-full" rows={1} aria-label={`What we do for ${r.control_id}`} value={r.customer_statement || ""} disabled={busy}
                                onChange={(e) => edit(r.control, { customer_statement: e.target.value })} />
                    ) : <span className="whitespace-pre-line text-muted">{r.customer_statement || "—"}</span>}
                  </td>
                  <td className="w-[90px] px-2 py-2">
                    {r.dirty ? <Badge tone="accent" mono>unsaved</Badge> : r.source ? <Badge tone="faint" mono>{r.source}</Badge> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canManage ? (
          <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface-2 px-5 py-3">
            <Button size="sm" variant="primary" disabled={busy || dirtyCount === 0 || orphaned.length > 0} onClick={saveEdits}>
              {busy ? "Saving…" : dirtyCount ? `Save ${dirtyCount} change(s)` : "Nothing to save"}
            </Button>
            {dirtyCount ? <Button size="sm" variant="ghost" onClick={() => setEdits({})} disabled={busy}>Discard</Button> : null}
            {orphaned.length ? (
              <span className="text-xs text-warning" role="status">
                {orphaned.map((r) => r.control_id).join(", ")}: pick a responsibility for the statement, or clear it.
              </span>
            ) : <Label>Clearing a responsibility removes the row and its statements.</Label>}
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

// --- Page --------------------------------------------------------------------------------

export default function Vendors({ me }) {
  const [params, setParams] = useSearchParams();
  const [vendors, setVendors] = useState(null);
  const [selectedId, setSelectedId] = useState(() => Number(params.get("vendor")) || null);
  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState(() => (TABS.some((t) => t.id === params.get("tab")) ? params.get("tab") : "overview"));
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState({ q: "", tier: "" });
  const [users, setUsers] = useState([]);
  const [docs, setDocs] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [intent, setIntent] = useState(null);
  const canManage = !!(me?.is_superuser || me?.capabilities?.manage_frameworks);

  async function loadVendors(keep = selectedId) {
    const rows = await fetchAll("/vendors/");
    setVendors(rows);
    const next = rows.find((v) => v.id === keep) || (keep ? null : rows[0]) || rows[0] || null;
    setSelectedId(next ? next.id : null);
  }
  async function loadDetail(id) {
    try {
      const { data } = await api.get(`/vendors/${id}/`);
      setDetail(data);
    } catch (e) {
      setDetail(null);
      setMsg({ ok: false, text: errorText(e, "Couldn't load that vendor.") });
    }
  }

  useEffect(() => {
    loadVendors().catch((e) => { setVendors([]); setMsg({ ok: false, text: errorText(e, "Couldn't load the vendor register.") }); });
    if (canManage) {
      fetchAll("/users/").then((u) => setUsers(u.filter((x) => x.is_active))).catch(() => setUsers([]));
      api.get("/control-evidence/choices/").then((r) => setDocs(r.data.documents || [])).catch(() => setDocs([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (selectedId) loadDetail(selectedId); else setDetail(null); }, [selectedId]);

  // Deep links from the notification tray: /vendors?vendor=3&tab=matrix.
  useEffect(() => {
    const v = Number(params.get("vendor")) || null;
    const t = TABS.some((x) => x.id === params.get("tab")) ? params.get("tab") : null;
    if (v && v !== selectedId) setSelectedId(v);
    if (t && t !== tab) setTab(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);
  useEffect(() => {
    const next = new URLSearchParams();
    if (selectedId) next.set("vendor", String(selectedId));
    if (tab !== "overview") next.set("tab", tab);
    if (next.toString() !== params.toString()) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, tab]);

  async function act(fn, okText) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      if (okText) setMsg({ ok: true, text: okText });
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }
  const refresh = async () => { await loadVendors(); if (selectedId) await loadDetail(selectedId); };

  const filtered = useMemo(() => (vendors || []).filter((v) =>
    (!filter.tier || v.tier === filter.tier)
    && (!filter.q || `${v.name} ${v.category} ${v.data_handled}`.toLowerCase().includes(filter.q.toLowerCase()))
  ), [vendors, filter]);
  const counts = useMemo(() => {
    const out = { critical: 0, high: 0, moderate: 0, low: 0 };
    for (const v of vendors || []) out[v.risk_rating] = (out[v.risk_rating] || 0) + 1;
    return out;
  }, [vendors]);

  const openAssessmentDoc = (r) => setViewing({
    title: r.document_name, subtitle: `${KIND_LABEL[r.kind] || r.kind} · ${detail?.name}`,
    previewUrl: `/documents/${r.document}/preview/`, downloadUrl: `/documents/${r.document}/download/`, filename: r.document_name,
    facts: [{ label: "Filed as", value: KIND_LABEL[r.kind] || r.kind }, { label: "Issued", value: fmtDate(r.issued_at) }, { label: "Expires", value: fmtDate(r.expires_at) }],
  });

  if (vendors === null) return <PanelTransition><Panel><Loading /></Panel></PanelTransition>;

  const needsMatrix = detail && detail.control_count === 0 && detail.status !== "offboarded";

  return (
    <PanelTransition>
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        {/* ------------------------------------------------------------ register */}
        <div className="flex flex-col gap-4">
          <Panel className="overflow-hidden">
            <PanelHeader title="Vendor register" meta={`${vendors.length} total`} />
            <div className="space-y-2 border-b border-line bg-surface-2 px-3 py-2.5">
              <label htmlFor="vendor-search" className="sr-only">Search vendors</label>
              <input id="vendor-search" className="input input-sm" placeholder="Search…" value={filter.q} onChange={(e) => setFilter((f) => ({ ...f, q: e.target.value }))} />
              <div className="flex flex-wrap gap-1">
                <Chip active={!filter.tier} onClick={() => setFilter((f) => ({ ...f, tier: "" }))}>All</Chip>
                {TIERS.map(([k, l]) => <Chip key={k} active={filter.tier === k} tone={TIER_TONE[k]} onClick={() => setFilter((f) => ({ ...f, tier: f.tier === k ? "" : k }))}>{l}</Chip>)}
              </div>
            </div>
            {filtered.length === 0 ? (
              <Empty title={vendors.length ? "No vendors match" : "No vendors yet"}>
                {vendors.length ? "Try another filter." : canManage ? "Register the third parties that touch your data or run your controls." : "Nothing has been registered yet."}
              </Empty>
            ) : (
              <ul className="max-h-[60vh] divide-y divide-line overflow-y-auto">
                {filtered.map((v) => {
                  const rating = RATING[v.risk_rating] || RATING.moderate;
                  return (
                    <li key={v.id}>
                      <button type="button" onClick={() => { setSelectedId(v.id); setTab("overview"); }} aria-current={v.id === selectedId || undefined}
                              className={cn("block w-full px-4 py-3 text-left transition-colors duration-150 ease-out", v.id === selectedId ? "bg-accent/10" : "hover:bg-surface-2")}>
                        <span className="flex items-center gap-2">
                          <Building2Icon className="h-3.5 w-3.5 shrink-0 text-faint" strokeWidth={2} aria-hidden="true" />
                          <span className="block truncate text-[13px] font-medium text-ink">{v.name}</span>
                        </span>
                        <span className="mt-1 flex flex-wrap items-center gap-1.5">
                          <Badge tone={TIER_TONE[v.tier]} mono>{v.tier}</Badge>
                          <Badge tone={rating.tone} dot>{rating.label} risk</Badge>
                          {v.control_count === 0 && v.status !== "offboarded" ? <Badge tone="warning" mono>no matrix</Badge> : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <Panel className="p-4">
            <Label className="mb-2 block">Risk mix</Label>
            <ul className="space-y-1.5">
              {Object.entries(RATING).map(([k, r]) => (
                <li key={k} className="flex items-center gap-2 text-xs">
                  <span className="h-2 w-2 rounded-[3px]" style={{ backgroundColor: `rgb(var(--${r.tone}))` }} aria-hidden="true" />
                  <span className="flex-1 text-muted">{r.label}</span>
                  <span className="tabular font-mono text-2xs text-ink">{counts[k] || 0}</span>
                </li>
              ))}
            </ul>
          </Panel>

          {canManage ? (
            <Panel className="p-4">
              {creating ? (
                <VendorForm users={users} busy={busy} submitLabel="Register vendor" onCancel={() => setCreating(false)}
                            onSubmit={(body) => act(async () => {
                              const { data } = await api.post("/vendors/", body);
                              setCreating(false);
                              await loadVendors(data.id);
                              setTab("matrix");
                              setIntent("prompt");
                            }, "Vendor registered. Next: state which controls they cover.")} />
              ) : (
                <Button size="sm" variant="primary" className="w-full" onClick={() => setCreating(true)}>Register a vendor</Button>
              )}
            </Panel>
          ) : null}
        </div>

        {/* -------------------------------------------------------------- detail */}
        <div className="flex min-w-0 flex-col gap-4">
          <Notice msg={msg} onClose={() => setMsg(null)} />
          {!selectedId || !detail ? (
            <Panel>{selectedId ? <Loading /> : <Empty title="Select a vendor">Pick a vendor on the left to see their assurance and responsibility matrix.</Empty>}</Panel>
          ) : (
            <>
              <Panel className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-[15px] font-semibold text-ink">{detail.name}</h2>
                    <p className="mt-0.5 text-xs text-muted">
                      {detail.category || "Third party"}{detail.website ? " · " : ""}
                      {detail.website ? <a href={detail.website} target="_blank" rel="noreferrer noopener" className="text-accent hover:underline">{hostOf(detail.website)}</a> : null}
                      {detail.owner_name ? ` · owned by ${detail.owner_name}` : ""}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={TIER_TONE[detail.tier]} mono>{detail.tier} tier</Badge>
                    <Badge tone={detail.status === "active" ? "success" : "muted"} dot>{detail.status_display}</Badge>
                    <Badge tone={(POSTURE[detail.assurance?.posture] || POSTURE.none).tone} dot>{(POSTURE[detail.assurance?.posture] || POSTURE.none).label}</Badge>
                  </div>
                </div>
                {needsMatrix ? (
                  <div className="notice notice-warn mt-4 flex flex-wrap items-center justify-between gap-3" role="status">
                    <span>
                      <span className="font-medium">New vendor — no responsibilities stated yet.</span>{" "}
                      Record which controls {detail.name} covers, or import their shared responsibility matrix, so the RACI view and audit packages can name them.
                    </span>
                    {canManage ? (
                      <span className="flex gap-2">
                        <Button size="sm" variant="primary" onClick={() => { setTab("matrix"); setIntent("prompt"); }}>Walk me through it</Button>
                        <Button size="sm" onClick={() => { setTab("matrix"); setIntent("import"); }}>Import their matrix</Button>
                      </span>
                    ) : null}
                  </div>
                ) : null}
                <div className="mt-4">
                  <SegmentedControl options={TABS} value={tab} onChange={setTab} layoutId="vendor-tabs" ariaLabel="Vendor sections" />
                </div>
              </Panel>

              {tab === "overview" ? (
                <OverviewTab vendor={detail} users={users} canManage={canManage} busy={busy}
                             onSave={(body) => act(async () => { await api.patch(`/vendors/${detail.id}/`, body); await refresh(); }, "Vendor updated.")}
                             onReviewed={() => act(async () => { await api.post(`/vendors/${detail.id}/mark_reviewed/`); await refresh(); }, "Review recorded; the next one is scheduled.")} />
              ) : tab === "assessments" ? (
                <AssessmentsTab vendor={detail} docs={docs} canManage={canManage} busy={busy} onOpen={openAssessmentDoc}
                                onFile={(body) => act(async () => { await api.post("/vendor-assessments/", body); await refresh(); }, "Filed.")}
                                onRemove={(r) => { if (window.confirm(`Remove this ${KIND_LABEL[r.kind] || r.kind} from the vendor's file?`)) act(async () => { await api.delete(`/vendor-assessments/${r.id}/`); await refresh(); }, "Removed."); }} />
              ) : tab === "questionnaire" ? (
                <QuestionnaireTab key={detail.id} vendor={detail} canManage={canManage} busy={busy} act={act} refresh={refresh}
                                  onSubmit={(body) => act(async () => { await api.post("/vendor-assessments/", body); await refresh(); }, "Questionnaire saved.")} />
              ) : (
                <MatrixTab vendor={detail} canManage={canManage} intent={intent} onIntentDone={() => setIntent(null)} setMsg={setMsg} onChanged={refresh} />
              )}
            </>
          )}
        </div>
      </div>
      <DocumentViewer open={!!viewing} {...(viewing || {})} onClose={() => setViewing(null)} />
    </PanelTransition>
  );
}
