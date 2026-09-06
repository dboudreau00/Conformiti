// The Conformiti identity: a shield split along its centreline with a single
// check struck across it, in four colourways. Governance Blue is the corporate
// mark; the other three are semantic and used where their meaning applies.
// Risk Red is reserved for findings and alert states, never the lockup.
export const BRAND_PALETTES = [
  { id: "green", name: "Assurance Green", role: "Controls passing, audit ready",
    base: "#0E9F6E", shade: "#08704D", soft: "#E9F7F1", onDark: "#34D399" },
  { id: "blue", name: "Governance Blue", role: "Primary corporate mark",
    base: "#1D6FE0", shade: "#12458F", soft: "#EAF1FD", onDark: "#60A5FA" },
  { id: "red", name: "Risk Red", role: "Findings, escalations, alerts",
    base: "#D93A3A", shade: "#8F2020", soft: "#FCECEC", onDark: "#F87171" },
  { id: "purple", name: "Policy Purple", role: "Frameworks and attestations",
    base: "#6D3BE4", shade: "#42208F", soft: "#F1EBFD", onDark: "#A78BFA" },
];

export const BRAND_DEFAULT = "blue";

export function paletteById(id) {
  return BRAND_PALETTES.find((p) => p.id === id) || BRAND_PALETTES[1];
}

// Geometry shared by the React component and the static SVG files in
// assets/brand and public/favicon.svg. Change it in one place.
export const SHIELD = "M32 3.5 L57 12.8 V32.6 C57 46.9 46.6 55.7 32 60.5 C17.4 55.7 7 46.9 7 32.6 V12.8 Z";
export const SHIELD_LEFT = "M32 3.5 L7 12.8 V32.6 C7 46.9 17.4 55.7 32 60.5 Z";
export const CHECK = "M19.5 32 L28.5 41 L45.5 22.5";
