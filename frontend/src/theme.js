// Theme engine: a theme *pack* (surfaces, ink, status colours) plus an accent
// *pack* (primary actions, active nav, highlights), persisted in localStorage
// and applied by swapping data-theme / data-accent on <html>. The tokens live
// in src/styles/index.css; /theme-init.js applies the saved values before the
// first paint. `useTheme()` keeps React components in sync.
import { useEffect, useState } from "react";

export const THEME_PACKS = [
  { id: "ledger", name: "Audit Ledger", mode: "Light", blurb: "Warm paper neutrals. Reads well in printed evidence packs.", swatch: ["#f6f5f1", "#ffffff"] },
  { id: "nimbus", name: "Nimbus", mode: "Light", blurb: "Cool slate. Highest legibility for long control reviews.", swatch: ["#f3f6fa", "#ffffff"] },
  { id: "ledger-dark", name: "Ledger Dark", mode: "Dark", blurb: "Muted ink surfaces for low-light monitoring.", swatch: ["#0c0e12", "#151820"] },
  { id: "obsidian", name: "Obsidian", mode: "Dark", blurb: "Near-black, maximum contrast for wall displays.", swatch: ["#060709", "#0d0f13"] },
];

export const ACCENT_PACKS = [
  { id: "pine", name: "Pine", hex: "#116e60" },
  { id: "azure", name: "Azure", hex: "#2563d8" },
  { id: "violet", name: "Violet", hex: "#764ae2" },
  { id: "ember", name: "Ember", hex: "#c23d34" },
];

export const DEFAULT_THEME = "ledger-dark";
export const DEFAULT_ACCENT = "azure";

// Names used by the pre-0.2 pages; kept so every page keeps compiling while
// it is ported to THEME_PACKS / ACCENT_PACKS.
export const THEMES = THEME_PACKS.map((t) => ({ id: t.id, label: t.name, mode: t.mode.toLowerCase(), swatch: t.swatch[1], bg: t.swatch[0] }));
export const ACCENT_PRESETS = ACCENT_PACKS.map((a) => ({ name: a.name, hex: a.hex }));

const LEGACY_THEMES = { blazor: "nimbus", "blazor-dark": "obsidian" };
const K_THEME = "theme";
const K_ACCENT = "accent";
const EVENT = "conformiti:theme";

const isHex = (v) => /^#[0-9a-f]{6}$/i.test(v || "");
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

export function getTheme() {
  const raw = store.get(K_THEME) || "";
  const mapped = LEGACY_THEMES[raw] || raw;
  return THEME_PACKS.some((t) => t.id === mapped) ? mapped : DEFAULT_THEME;
}

/** Accent pack id, or a custom "#rrggbb". */
export function getAccent() {
  const raw = store.get(K_ACCENT) || "";
  if (ACCENT_PACKS.some((a) => a.id === raw)) return raw;
  if (isHex(raw)) return raw.toLowerCase();
  return DEFAULT_ACCENT;
}

export const isDark = (id = getTheme()) => id === "ledger-dark" || id === "obsidian";

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Resolve the accent's hex for swatches (custom or pack). */
export function accentHex(id = getAccent()) {
  if (isHex(id)) return id;
  return (ACCENT_PACKS.find((a) => a.id === id) || ACCENT_PACKS[1]).hex;
}

function apply() {
  const root = document.documentElement;
  root.setAttribute("data-theme", getTheme());
  const accent = getAccent();
  if (isHex(accent)) {
    const [r, g, b] = hexToRgb(accent);
    root.setAttribute("data-accent", "custom");
    root.style.setProperty("--accent", `${r} ${g} ${b}`);
    const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    root.style.setProperty("--accent-ink", lum > 0.6 ? "10 12 16" : "255 255 255");
  } else {
    root.setAttribute("data-accent", accent);
    root.style.removeProperty("--accent");
    root.style.removeProperty("--accent-ink");
  }
  window.dispatchEvent(new CustomEvent(EVENT));
}

export function setTheme(id) {
  store.set(K_THEME, THEME_PACKS.some((t) => t.id === id) ? id : DEFAULT_THEME);
  apply();
}

export function setAccent(idOrHex) {
  if (!idOrHex) store.del(K_ACCENT);
  else store.set(K_ACCENT, idOrHex);
  apply();
}

/** Flip between the light/dark sibling of the current pack. */
export function toggleMode() {
  const cur = getTheme();
  const next = { ledger: "ledger-dark", "ledger-dark": "ledger", nimbus: "obsidian", obsidian: "nimbus" }[cur] || DEFAULT_THEME;
  setTheme(next);
}

export function initTheme() {
  apply();
}

/** React hook: current theme/accent plus setters, re-rendering on change. */
export function useTheme() {
  const [state, setState] = useState(() => ({ theme: getTheme(), accent: getAccent() }));
  useEffect(() => {
    const sync = () => setState({ theme: getTheme(), accent: getAccent() });
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return { ...state, isDark: isDark(state.theme), setTheme, setAccent, toggleMode };
}
