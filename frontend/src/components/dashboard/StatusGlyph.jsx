import { cn } from "../../utils/cn.js";
import { toneVar } from "../../utils/tone.js";

/** Status is never shown by colour alone: solid, half filled, empty outline and hatched read apart in greyscale. */
export const STATUS_FILL = {
  implemented: {
    background: toneVar("success"),
    borderColor: toneVar("success"),
  },
  in_progress: {
    background: `linear-gradient(to top, ${toneVar("warning")} 50%, transparent 50%)`,
    borderColor: toneVar("warning"),
    borderWidth: "1.5px",
  },
  not_started: {
    background: "transparent",
    borderColor: toneVar("faint", 0.6),
  },
  not_applicable: {
    background: `repeating-linear-gradient(135deg, ${toneVar("faint", 0.6)} 0 1px, transparent 1px 4px)`,
    borderColor: "transparent",
  },
};

export function StatusGlyph({ status, size = 11, className }) {
  return (
    <i
      aria-hidden="true"
      className={cn("inline-block shrink-0 rounded-[3px] border align-[-1px]", className)}
      style={{ width: size, height: size, ...(STATUS_FILL[status] || STATUS_FILL.not_started) }}
    />
  );
}
