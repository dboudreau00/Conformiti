import { useEffect, useState } from "react";
import { SendIcon, XIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";
import { RISK_RATING, RISK_STATUS } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { Button, IconButton } from "../ui/Button.jsx";
import { Label, Loading, Panel } from "../ui/Panel.jsx";
import { Field } from "./Field.jsx";
import { IMPACT_WORDS, LIKELIHOOD_WORDS, SCALE, STATUSES, TREATMENTS, treatmentLabel } from "./vocab.js";

const displayName = (u) => u.full_name || u.username || `User ${u.id}`;
const day = (iso) => (iso ? String(iso).slice(0, 10) : "");

/**
 * The selected risk: description, the treatment fields (editable for a
 * framework manager or the risk's owner — the same rule as RiskPermission),
 * the mitigation plan and the progress-note thread (anyone may add a note).
 */
export function RiskDetail({
  risk,
  canEdit,
  users,
  usersErr,
  saving,
  notice,
  onPatch,
  onClose,
  notes,
  notesLoading,
  notesErr,
  addingNote,
  onAddNote,
}) {
  const [planDraft, setPlanDraft] = useState(risk.mitigation_plan || "");
  const [jiraDraft, setJiraDraft] = useState(risk.jira_key || "");
  const [noteText, setNoteText] = useState("");

  useEffect(() => setPlanDraft(risk.mitigation_plan || ""), [risk.id, risk.mitigation_plan]);
  useEffect(() => setJiraDraft(risk.jira_key || ""), [risk.id, risk.jira_key]);
  useEffect(() => setNoteText(""), [risk.id]);

  const status = RISK_STATUS[risk.status] || { label: risk.status, tone: "muted" };
  const ratingTone = RISK_RATING[risk.rating] || "muted";
  const planDirty = planDraft !== (risk.mitigation_plan || "");
  const id = (suffix) => `risk-${risk.id}-${suffix}`;
  // Fall back to the current owner alone if the directory could not be loaded,
  // so the select never silently drops the assignment.
  const ownerOptions = users.length ? users : risk.owner ? [{ id: risk.owner, full_name: risk.owner_name }] : [];

  function commitJira() {
    const next = jiraDraft.trim();
    if (next !== (risk.jira_key || "")) onPatch({ jira_key: next });
  }

  async function submitNote(e) {
    e.preventDefault();
    const text = noteText.trim();
    if (!text || addingNote) return;
    const ok = await onAddNote(text);
    if (ok) setNoteText("");
  }

  return (
    <Panel className="p-5" aria-labelledby={id("title")}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Label className="block truncate">
            #{risk.id} · identified {risk.identified_on || "—"} · by {risk.created_by_name || "—"}
            {risk.closed_at ? ` · closed ${day(risk.closed_at)}` : ""}
          </Label>
          <h3 id={id("title")} className="mt-1 text-[15px] font-semibold text-ink">
            {risk.title}
          </h3>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge tone={status.tone} dot mono>
            {status.label}
          </Badge>
          <IconButton label="Close details" onClick={onClose}>
            <XIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
          </IconButton>
        </div>
      </div>

      <p className={cn("mt-3 max-w-[70ch] whitespace-pre-line text-[13px] leading-relaxed", risk.description ? "text-muted" : "text-faint")}>
        {risk.description || "No description recorded."}
      </p>

      {notice ? (
        <div className={cn("notice mt-4", notice.ok ? "notice-ok" : "notice-err")} role={notice.ok ? "status" : "alert"}>
          {notice.text}
        </div>
      ) : null}

      {canEdit ? (
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4" aria-busy={saving}>
          <Field id={id("status")} label="Status">
            <select id={id("status")} className="input input-sm" value={risk.status} disabled={saving} onChange={(e) => onPatch({ status: e.target.value })}>
              {STATUSES.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </Field>
          <Field id={id("treatment")} label="Treatment">
            <select id={id("treatment")} className="input input-sm" value={risk.treatment} disabled={saving} onChange={(e) => onPatch({ treatment: e.target.value })}>
              {TREATMENTS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </Field>
          <Field id={id("likelihood")} label="Likelihood">
            <select id={id("likelihood")} className="input input-sm" value={risk.likelihood} disabled={saving} onChange={(e) => onPatch({ likelihood: Number(e.target.value) })}>
              {SCALE.map((n) => (
                <option key={n} value={n}>{n} · {LIKELIHOOD_WORDS[n - 1]}</option>
              ))}
            </select>
          </Field>
          <Field id={id("impact")} label="Impact">
            <select id={id("impact")} className="input input-sm" value={risk.impact} disabled={saving} onChange={(e) => onPatch({ impact: Number(e.target.value) })}>
              {SCALE.map((n) => (
                <option key={n} value={n}>{n} · {IMPACT_WORDS[n - 1]}</option>
              ))}
            </select>
          </Field>
          <Field id={id("owner")} label="Owner">
            <select id={id("owner")} className="input input-sm" value={risk.owner ?? ""} disabled={saving} onChange={(e) => onPatch({ owner: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Unassigned</option>
              {ownerOptions.map((u) => (
                <option key={u.id} value={u.id}>{displayName(u)}</option>
              ))}
            </select>
            {usersErr ? <p className="mt-1 text-2xs text-danger">{usersErr}</p> : null}
          </Field>
          <Field id={id("due")} label="Due date">
            <input id={id("due")} type="date" className="input input-sm" value={risk.due_date || ""} disabled={saving} onChange={(e) => onPatch({ due_date: e.target.value || null })} />
          </Field>
          <Field id={id("jira")} label="Jira key">
            <input
              id={id("jira")}
              className="input input-sm font-mono"
              value={jiraDraft}
              placeholder="SEC-101"
              maxLength={40}
              disabled={saving}
              onChange={(e) => setJiraDraft(e.target.value)}
              onBlur={commitJira}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitJira();
                }
              }}
            />
          </Field>
          <div className="min-w-0">
            <span className="field-label">Rating</span>
            <div className="flex h-8 items-center gap-2">
              <Badge tone={ratingTone} mono>
                {risk.rating} · {risk.score}
              </Badge>
              <span className="tabular font-mono text-2xs text-faint">
                L{risk.likelihood} × I{risk.impact}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <dt><Label>Rating</Label></dt>
            <dd className="mt-1">
              <Badge tone={ratingTone} mono>
                {risk.rating} · {risk.score}
              </Badge>
            </dd>
          </div>
          <div>
            <dt><Label>Score</Label></dt>
            <dd className="tabular mt-1 font-mono text-[13px] text-ink">
              L{risk.likelihood} × I{risk.impact} = {risk.score}
            </dd>
          </div>
          <div>
            <dt><Label>Treatment</Label></dt>
            <dd className="mt-1 text-[13px] text-ink">{treatmentLabel(risk.treatment)}</dd>
          </div>
          <div>
            <dt><Label>Owner</Label></dt>
            <dd className={cn("mt-1 truncate text-[13px]", risk.owner_name ? "text-ink" : "text-danger")}>{risk.owner_name || "Unassigned"}</dd>
          </div>
          <div>
            <dt><Label>Due</Label></dt>
            <dd className={cn("tabular mt-1 font-mono text-[13px]", risk.is_overdue ? "text-danger" : "text-ink")}>{risk.due_date || "—"}</dd>
          </div>
          <div>
            <dt><Label>Jira</Label></dt>
            <dd className="mt-1 font-mono text-[13px] text-ink">{risk.jira_key || "—"}</dd>
          </div>
        </dl>
      )}

      {/* ---------------------------------------------------------- mitigation plan */}
      <div className="mt-5">
        <div className="flex min-h-[28px] items-center justify-between gap-3">
          {canEdit ? (
            <Label as="label" htmlFor={id("plan")}>Mitigation plan</Label>
          ) : (
            <Label>Mitigation plan</Label>
          )}
          {canEdit && planDirty ? (
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" disabled={saving} onClick={() => setPlanDraft(risk.mitigation_plan || "")}>
                Discard
              </Button>
              <Button size="sm" variant="primary" disabled={saving} onClick={() => onPatch({ mitigation_plan: planDraft })}>
                {saving ? "Saving…" : "Save plan"}
              </Button>
            </div>
          ) : null}
        </div>
        {canEdit ? (
          <textarea
            id={id("plan")}
            className="input mt-1.5"
            rows={3}
            value={planDraft}
            disabled={saving}
            placeholder="How will this risk be reduced, transferred or avoided?"
            onChange={(e) => setPlanDraft(e.target.value)}
          />
        ) : (
          <p className={cn("mt-1.5 max-w-[70ch] whitespace-pre-line text-[13px] leading-relaxed", risk.mitigation_plan ? "text-ink" : "text-faint")}>
            {risk.mitigation_plan || "No plan recorded yet."}
          </p>
        )}
      </div>

      {/* ---------------------------------------------------------- notes */}
      <div className="mt-5 border-t border-line pt-4">
        <div className="flex items-center justify-between gap-3">
          <Label>Progress notes</Label>
          <Label className="tabular">{notes.length}</Label>
        </div>

        {notesErr ? (
          <div className="notice notice-err mt-2" role="alert">{notesErr}</div>
        ) : notesLoading ? (
          <Loading className="py-6">Loading notes…</Loading>
        ) : notes.length === 0 ? (
          <p className="mt-2 text-xs text-faint">No notes yet. Add the first progress note below.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {notes.map((n) => (
              <li key={n.id} className="py-2.5">
                <p className="font-mono text-2xs text-faint">
                  <span className="text-muted">{n.author_name || "—"}</span> · {day(n.created_at) || "—"}
                </p>
                <p className="mt-0.5 whitespace-pre-line text-[13px] leading-relaxed text-ink">{n.text}</p>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={submitNote} className="mt-3 flex items-end gap-2">
          <div className="min-w-0 flex-1">
            <label htmlFor={id("note")} className="field-label">Add a progress note</label>
            <input
              id={id("note")}
              className="input input-sm"
              value={noteText}
              placeholder="What changed?"
              maxLength={2000}
              disabled={addingNote}
              onChange={(e) => setNoteText(e.target.value)}
            />
          </div>
          <Button
            type="submit"
            size="sm"
            className="h-8"
            disabled={addingNote || !noteText.trim()}
            icon={<SendIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
          >
            {addingNote ? "Adding…" : "Add note"}
          </Button>
        </form>
      </div>
    </Panel>
  );
}
