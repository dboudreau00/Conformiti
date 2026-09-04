import { motion } from "framer-motion";
import { cn } from "../../utils/cn.js";
import { TONE_TEXT } from "../../utils/tone.js";
import { Label, Panel } from "./Panel.jsx";

export function StatCard({ label, value, suffix, detail, tone, children, className }) {
  return (
    <Panel className={cn("flex flex-col gap-1 p-4", className)}>
      <Label>{label}</Label>
      <div className="flex items-baseline gap-1">
        <motion.span
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.23, 1, 0.32, 1] }}
          className={cn("tabular text-[30px] font-semibold leading-none tracking-[-0.03em]", tone && TONE_TEXT[tone] ? TONE_TEXT[tone] : "text-ink")}
        >
          {value}
        </motion.span>
        {suffix ? <span className="tabular text-base font-medium text-faint">{suffix}</span> : null}
      </div>
      {detail ? <p className="text-xs leading-snug text-muted">{detail}</p> : null}
      {children}
    </Panel>
  );
}
