/** Tailwind maps every colour to a CSS token (raw RGB triple) so utilities can
 * carry alpha (`bg-accent/10`) and every theme/accent pack re-colours the whole
 * product by swapping the tokens on <html>. See src/styles/index.css. */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        "line-strong": "rgb(var(--line-strong) / <alpha-value>)",
        grid: "rgb(var(--grid) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-ink": "rgb(var(--accent-ink) / <alpha-value>)",
        success: "rgb(var(--success) / <alpha-value>)",
        warning: "rgb(var(--warning) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        info: "rgb(var(--info) / <alpha-value>)",
      },
      // Stacks, not downloads: Inter and JetBrains Mono are used when the
      // reader already has them, and the platform's own UI faces otherwise.
      // Nothing is fetched from a font CDN -- see index.html.
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system",
               "Segoe UI", "Roboto", "Helvetica Neue", "Arial",
               "Noto Sans", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo",
               "Consolas", "Liberation Mono", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      letterSpacing: {
        label: "0.09em",
      },
      borderRadius: {
        panel: "14px",
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
        pop: "var(--shadow-pop)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.23, 1, 0.32, 1)",
        smooth: "cubic-bezier(0.65, 0, 0.35, 1)",
      },
    },
  },
  plugins: [],
};
