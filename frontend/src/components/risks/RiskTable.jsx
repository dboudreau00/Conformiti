import { motion } from "framer-motion";
import { MessageSquareIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";
import { fmtDate } from "../../utils/format.js";
import { RISK_RATING, RISK_STATUS, dueLabel } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { daysUntil, isLive, typeLabel } from "./vocab.js";

const HEAD = "table-head px-3 py-2 font-normal";

export function RiskTable({ risks, selectedId, onSelect }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] table-fixed border-collapse text-left">
        <thead>
          <tr className="border-b border-line bg-surface-2">
            <th scope="col" className={cn(HEAD, "px-5")}>Risk</th>
            <th scope="col" className={cn(HEAD, "w-[118px]")}>Rating</th>
            <th scope="col" className={cn(HEAD, "w-[140px]")}>Owner</th>
            <th scope="col" className={cn(HEAD, "w-[124px]")}>Due</th>
            <th scope="col" className={cn(HEAD, "w-[118px]")}>Status</th>
            <th scope="col" className={cn(HEAD, "w-[72px] px-5 text-right")}>Notes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {risks.map((r) => (
            <RiskRow key={r.id} risk={r} active={r.id === selectedId} onSelect={() => onSelect(r)} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RiskRow({ risk, active, onSelect }) {
  const status = RISK_STATUS[risk.status] || { label: risk.status, tone: "muted" };
  const days = isLive(risk) ? daysUntil(risk.due_date) : null;

  return (
    // The row keeps its table semantics (cells read against their column headings); the title is the real control, and a
    // click anywhere on the row is the same toggle for a pointer.
    <tr
      onClick={onSelect}
      className={cn(
        "cursor-pointer transition-colors duration-150 ease-out hover:bg-surface-2 has-[:focus-visible]:bg-surface-2",
        active && "bg-surface-2"
      )}
    >
      <td className="relative px-5 py-3 align-middle">
        {active ? (
          <motion.span
            layoutId="risk-row"
            className="absolute inset-y-0 left-0 w-[2px] bg-accent"
            transition={{ type: "spring", stiffness: 520, damping: 38 }}
            aria-hidden="true"
          />
        ) : null}
        <button
          type="button"
          aria-pressed={active}
          title={risk.title}
          className="block w-full truncate text-left text-[13px] font-medium text-ink"
        >
          {risk.title}
        </button>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-muted">
          <span className="tabular font-mono text-faint">#{risk.id}</span>
          <span>{typeLabel(risk.risk_type)}</span>
          {risk.control_label ? (
            <span
              className="rounded border border-line bg-surface px-1.5 font-mono text-2xs text-muted"
              title={risk.control_framework || undefined}
            >
              {risk.control_label}
            </span>
          ) : null}
          {risk.jira_key ? <span className="font-mono text-faint">{risk.jira_key}</span> : null}
        </span>
      </td>

      <td className="px-3 py-3 align-middle">
        <Badge tone={RISK_RATING[risk.rating] || "muted"} mono>
          {risk.rating} · {risk.score}
        </Badge>
      </td>

      <td
        className={cn("truncate px-3 py-3 align-middle text-xs", risk.owner_name ? "text-muted" : "text-danger")}
        title={risk.owner_name || undefined}
      >
        {risk.owner_name || "Unassigned"}
      </td>

      <td className={cn("tabular px-3 py-3 align-middle font-mono text-xs", risk.is_overdue ? "text-danger" : "text-muted")}>
        {fmtDate(risk.due_date)}
        {days != null ? (
          <span className={cn("block text-2xs", risk.is_overdue ? "text-danger" : "text-faint")}>{dueLabel(days)}</span>
        ) : null}
      </td>

      <td className="px-3 py-3 align-middle">
        <Badge tone={status.tone} dot>
          {status.label}
        </Badge>
      </td>

      <td className="px-5 py-3 text-right align-middle">
        <span className="tabular inline-flex items-center gap-1 font-mono text-xs text-muted">
          <MessageSquareIcon className="h-3 w-3 text-faint" strokeWidth={2} aria-hidden="true" />
          {risk.note_count || 0}
        </span>
      </td>
    </tr>
  );
}
