// Theme engine — theme (family + light/dark) and a custom accent colour,
// persisted in localStorage and applied by swapping CSS custom properties.
// The early inline script in index.html applies the saved values before React
// mounts (no flash); initTheme() re-applies on load.

export const THEMES = [
  { id: "ledger", label: "Audit Ledger", mode: "light", swatch: "#0f766e", bg: "#eef1f4" },
  { id: "ledger-dark", label: "Ledger Dark", mode: "dark", swatch: "#2dd4bf", bg: "#0e151c" },
  { id: "blazor", label: "Blazor", mode: "light", swatch: "#1b6ec2", bg: "#f0f2f5" },
  { id: "blazor-dark", label: "Blazor Dark", mode: "dark", swatch: "#3b82f6", bg: "#12161c" },
];
export const DEFAULT_THEME = "ledger";

export const ACCENT_PRESETS = [
  { name: "Teal", hex: "#0f766e" },
  { name: "Blue", hex: "#1b6ec2" },
  { name: "Indigo", hex: "#4f46e5" },
  { name: "Violet", hex: "#7c3aed" },
  { name: "Emerald", hex: "#059669" },
  { name: "Rose", hex: "#e11d48" },
  { name: "Amber", hex: "#d97706" },
];

const K_THEME = "theme";
const K_ACCENT = "accent";
const K_ACCENT_VARS = "accentVars";

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

function hexToRgb(hex) {
  let h = String(hex).replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
function rgbStr(hex) { const { r, g, b } = hexToRgb(hex); return `${r},${g},${b}`; }
function rgbToHex(r, g, b) {
  const s = (v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0");
  return `#${s(r)}${s(g)}${s(b)}`;
}
function rgbToHsl({ r, g, b }) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0; const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
  }
  return { h: h * 360, s: s * 100, l: l * 100 };
}
function hslToHex(h, s, l) {
  h /= 360; s /= 100; l /= 100;
  const f = (p, q, t) => {
    if (t < 0) t += 1; if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  let r, g, b;
  if (s === 0) { r = g = b = l; }
  else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = f(p, q, h + 1 / 3); g = f(p, q, h); b = f(p, q, h - 1 / 3);
  }
  return rgbToHex(r * 255, g * 255, b * 255);
}

// Derive the accent family (primary / darker / brighter / tint / text) from one
// colour. Status colours (success, warning, overdue) are intentionally left to
// the active theme so they stay meaningful.
export function deriveAccent(hex, mode = "light") {
  const { h, s, l } = rgbToHsl(hexToRgb(hex));
  const accent = hslToHex(h, s, clamp(l, 22, 66));
  return {
    "--accent": accent,
    "--accent-2": hslToHex(h, s, clamp(l - 10, 12, 58)),
    "--accent-bright": hslToHex(h, clamp(s + 4, 0, 100), clamp(l + 14, 30, 82)),
    "--accent-bg": mode === "dark" ? `rgba(${rgbStr(hex)},0.16)` : hslToHex(h, clamp(s - 12, 0, 100), 94),
    "--on-accent": rgbToHsl(hexToRgb(accent)).l > 55 ? "#0a0f14" : "#ffffff",
    "--focus-ring": `rgba(${rgbStr(accent)},0.28)`,
  };
}

const rootStyle = () => document.documentElement.style;
const applyVars = (vars) => Object.entries(vars).forEach(([k, v]) => rootStyle().setProperty(k, v));
const ACCENT_KEYS = ["--accent", "--accent-2", "--accent-bright", "--accent-bg", "--on-accent", "--focus-ring"];

export const getTheme = () => localStorage.getItem(K_THEME) || DEFAULT_THEME;
export const getAccent = () => localStorage.getItem(K_ACCENT) || "";
const themeMode = (id) => (THEMES.find((t) => t.id === id) || {}).mode || "light";

export function setTheme(id) {
  localStorage.setItem(K_THEME, id);
  document.documentElement.setAttribute("data-theme", id);
  const accent = getAccent();
  if (accent) setAccent(accent);   // re-derive tint/contrast for the new mode
}

export function setAccent(hex) {
  if (!hex) {
    localStorage.removeItem(K_ACCENT);
    localStorage.removeItem(K_ACCENT_VARS);
    ACCENT_KEYS.forEach((k) => rootStyle().removeProperty(k));
    return;
  }
  const vars = deriveAccent(hex, themeMode(getTheme()));
  localStorage.setItem(K_ACCENT, hex);
  localStorage.setItem(K_ACCENT_VARS, JSON.stringify(vars));
  applyVars(vars);
}

export function initTheme() {
  document.documentElement.setAttribute("data-theme", getTheme());
  try {
    const vars = JSON.parse(localStorage.getItem(K_ACCENT_VARS) || "null");
    if (vars) applyVars(vars);
  } catch { /* ignore malformed cache */ }
}
