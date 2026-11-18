import { useLocation } from "react-router-dom";

// Where the strongest pool of light sits: the dashboard leads from the left, the register from the right, the audit
// package from above. Every other page takes the dashboard's.
const GLOW = { "/": "left", "/controls": "right", "/packages": "center" };

/** The edge light behind a page. Drawn by the Conformiti packs only (styles/index.css, `.backlight`); `variant`
 * overrides the one the route would pick. Its parent must isolate, so it sits above the page's own background. */
export function Backlight({ variant }) {
  const { pathname } = useLocation();
  return <div className="backlight" data-glow={variant || GLOW[pathname] || "left"} aria-hidden="true" />;
}
