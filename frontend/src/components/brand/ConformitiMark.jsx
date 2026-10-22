/**
 * The Conformiti mark: a shield split along its centreline, a check knocked
 * out in white across it. Solid by default; `outline` for stamps and small
 * monochrome uses.
 *
 * `colour` is one of the four brand colourways, which stay put whatever the
 * theme (the lighter `onDark` tint on the dark packs unless `onDark` is
 * forced), or "accent": the shield takes the theme's accent, its darker half
 * the accent's deep shade, so it changes when the accent does.
 */
import { useEffect, useState } from "react";
import { CHECK, SHIELD, SHIELD_LEFT, paletteById } from "../../brand.js";
import { isDark } from "../../theme.js";

function useDarkTheme() {
  const [dark, setDark] = useState(() => isDark());
  useEffect(() => {
    const sync = () => setDark(isDark());
    window.addEventListener("conformiti:theme", sync);
    return () => window.removeEventListener("conformiti:theme", sync);
  }, []);
  return dark;
}

export function ConformitiMark({ colour = "blue", markStyle = "solid", size = 32, onDark, title, className }) {
  const themeDark = useDarkTheme();
  const dark = onDark === undefined ? themeDark : onDark;
  const palette = paletteById(colour);
  const followsAccent = colour === "accent";
  const accent = followsAccent ? "rgb(var(--accent))" : dark ? palette.onDark : palette.base;
  const deep = followsAccent ? "rgb(var(--accent-deep))" : dark ? palette.base : palette.shade;
  const labelled = !!title;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"
         role={labelled ? "img" : "presentation"} aria-label={labelled ? title : undefined}
         aria-hidden={labelled ? undefined : true} className={className}>
      {markStyle === "solid" ? (
        <>
          <path d={SHIELD} style={{ fill: accent }} />
          <path d={SHIELD_LEFT} style={{ fill: deep }} />
          <path d={CHECK} stroke="#FFFFFF" strokeWidth={6} strokeLinecap="round" strokeLinejoin="round" />
        </>
      ) : (
        <>
          <path d={SHIELD} style={{ stroke: accent }} strokeWidth={4.5} strokeLinejoin="round" />
          <path d={CHECK} style={{ stroke: accent }} strokeWidth={5.5} strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
    </svg>
  );
}
