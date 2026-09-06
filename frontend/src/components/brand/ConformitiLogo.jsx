/**
 * The logo lockup: mark plus wordmark ("Conform" in ink, "iti" in the
 * colourway). Horizontal for headers, stacked for cover screens, `mark` alone
 * below 20px where the wordmark stops resolving.
 */
import { paletteById } from "../../brand.js";
import { cn } from "../../utils/cn.js";
import { ConformitiMark } from "./ConformitiMark.jsx";

export function ConformitiLogo({ colour = "blue", lockup = "horizontal", size = 36, tagline, className }) {
  const palette = paletteById(colour);
  if (lockup === "mark") {
    return <ConformitiMark colour={colour} size={size} title="Conformiti" className={className} />;
  }
  const stacked = lockup === "stacked";
  const wordSize = Math.round(size * (stacked ? 0.52 : 0.5));
  return (
    <div className={cn("flex", stacked ? "flex-col items-center text-center" : "flex-row items-center", className)}
         style={{ gap: Math.round(size * (stacked ? 0.28 : 0.3)) }}>
      <ConformitiMark colour={colour} size={size} title="Conformiti" />
      <div className={cn("flex flex-col", stacked ? "items-center" : "items-start")}>
        <span className="font-semibold leading-none tracking-[-0.035em] text-ink" style={{ fontSize: wordSize }}>
          Conform<span style={{ color: palette.base }}>iti</span>
        </span>
        {tagline ? (
          <span className="font-mono text-2xs uppercase tracking-label text-faint" style={{ marginTop: Math.round(wordSize * 0.4) }}>
            {tagline}
          </span>
        ) : null}
      </div>
    </div>
  );
}
