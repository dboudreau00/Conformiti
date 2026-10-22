// Theme engine: a theme *pack* (surfaces, ink, status colours) plus an accent
// *pack* (primary actions, active nav, highlights), persisted in localStorage
// and applied by swapping data-theme / data-accent on <html>. The tokens live
// in src/styles/index.css; /theme-init.js applies the saved values before the
// first paint. `useTheme()` keeps React components in sync.
import { useEffect, useState } from "react";
import { CHECK, SHIELD, SHIELD_LEFT } from "./brand.js";

export const THEME_PACKS = [
  { id: "ledger", name: "Audit Ledger", mode: "Light", swatch: ["#f6f5f1", "#ffffff"] },
  { id: "nimbus", name: "Nimbus", mode: "Light", swatch: ["#f3f6fa", "#ffffff"] },
  { id: "ledger-dark", name: "Ledger Dark", mode: "Dark", swatch: ["#0c0e12", "#151820"] },
  { id: "obsidian", name: "Obsidian", mode: "Dark", swatch: ["#060709", "#0d0f13"] },
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

/** "92 150 250" -> "#5c96fa", for the one place a token cannot be used: the tab icon is an image. */
const tripleToHex = (triple) => `#${triple.trim().split(/\s+/).map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;

const isTriple = (value) => /^\s*\d+\s+\d+\s+\d+\s*$/.test(value);
const toRgb = (triple) => triple.trim().split(/\s+/).map(Number);

// WCAG 2 contrast between two sRGB triples, and `top` washed into `base` at `alpha` (what a `bg-accent/10` paints).
const channel = (v) => {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = ([r, g, b]) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
const wash = (top, base, alpha) => base.map((v, i) => v * (1 - alpha) + top[i] * alpha);

/** The accent as small text, or null when the accent itself will do. It is read on the page, on a card, on its own 10% wash
 *  (a badge, an active chip) and on that wash stacked on a selected row's, and must hold 4.5:1 on all of them. One that does
 *  not (a mid-tone custom colour, Violet or Ember on some packs) moves toward the pack's ink as little as will clear 4.6:1.
 *  Only `text-accent` reads this; fills, borders and washes keep the accent as chosen. */
function accentText(accent, style) {
  const tokens = ["--bg", "--surface", "--surface-2", "--ink"].map((name) => style.getPropertyValue(name));
  if (!tokens.every(isTriple)) return null;
  const [page, card, raised, ink] = tokens.map(toRgb);
  const grounds = [page, card, raised].flatMap((base) => [base, wash(accent, base, 0.1)]);
  grounds.push(wash(accent, wash(accent, card, 0.1), 0.1));
  const holds = (text, bar) => grounds.every((ground) => contrast(text, ground) >= bar);
  if (holds(accent, 4.5)) return null;
  for (let t = 0.02; t < 1; t += 0.02) {
    const text = accent.map((v, i) => v + (ink[i] - v) * t);
    if (holds(text, 4.6)) return text.map(Math.round);
  }
  return ink;
}

/** The parts of the browser around the page follow the theme too, rebuilt whenever it changes: the tab icon is the shield
 *  in the current accent (a data: image, which the shipped Content-Security-Policy allows, img-src 'self' data: blob:;
 *  /favicon.svg stays the fallback) and the address bar a phone draws takes the pack's background. */
function paintChrome() {
  const style = getComputedStyle(document.documentElement);
  const link = document.querySelector('link[rel~="icon"]');
  const right = style.getPropertyValue("--accent");
  const left = style.getPropertyValue("--accent-deep");
  if (link && isTriple(right) && isTriple(left)) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">`
      + `<path d="${SHIELD}" fill="${tripleToHex(right)}"/><path d="${SHIELD_LEFT}" fill="${tripleToHex(left)}"/>`
      + `<path d="${CHECK}" stroke="#ffffff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    link.setAttribute("href", `data:image/svg+xml,${encodeURIComponent(svg)}`);
  }
  const bar = document.querySelector('meta[name="theme-color"]');
  const bg = style.getPropertyValue("--bg");
  if (bar && isTriple(bg)) bar.setAttribute("content", tripleToHex(bg));
}

function apply() {
  const root = document.documentElement;
  root.setAttribute("data-theme", getTheme());
  const accent = getAccent();
  if (isHex(accent)) {
    const [r, g, b] = hexToRgb(accent);
    root.setAttribute("data-accent", "custom");
    root.style.setProperty("--accent", `${r} ${g} ${b}`);
    // The label on the fill is whichever of white and the dark ink reads better on it (a mid-tone like #e91e63 takes the dark).
    root.style.setProperty("--accent-ink", contrast([r, g, b], [255, 255, 255]) >= contrast([r, g, b], [10, 12, 16]) ? "255 255 255" : "10 12 16");
    // The shield's darker half: the accent at about two thirds, as the packs' own shades are.
    root.style.setProperty("--accent-deep", `${Math.round(r * 0.62)} ${Math.round(g * 0.62)} ${Math.round(b * 0.62)}`);
  } else {
    root.setAttribute("data-accent", accent);
    root.style.removeProperty("--accent");
    root.style.removeProperty("--accent-ink");
    root.style.removeProperty("--accent-deep");
  }
  const style = getComputedStyle(root);
  const resolved = style.getPropertyValue("--accent");
  const text = isTriple(resolved) ? accentText(toRgb(resolved), style) : null;
  if (text) root.style.setProperty("--accent-text", text.join(" "));
  else root.style.removeProperty("--accent-text");
  paintChrome();
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
