// Applies the saved theme pack + accent before React mounts, so there is no
// flash of the wrong theme. Kept as a separate file (not inline) so the
// Content-Security-Policy can stay `script-src 'self'`. Mirrors src/theme.js.
(function () {
  try {
    var THEMES = ["ledger", "nimbus", "ledger-dark", "obsidian"];
    var ACCENTS = ["pine", "azure", "violet", "ember"];
    var LEGACY = { blazor: "nimbus", "blazor-dark": "obsidian" };
    var root = document.documentElement;
    var t = localStorage.getItem("theme") || "";
    t = LEGACY[t] || t;
    if (THEMES.indexOf(t) < 0) t = "ledger-dark";
    root.setAttribute("data-theme", t);
    var a = localStorage.getItem("accent") || "";
    if (ACCENTS.indexOf(a) >= 0) {
      root.setAttribute("data-accent", a);
    } else if (/^#[0-9a-f]{6}$/i.test(a)) {
      var n = parseInt(a.slice(1), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
      root.setAttribute("data-accent", "custom");
      root.style.setProperty("--accent", r + " " + g + " " + b);
      var lin = function (c) { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
      var lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      // White or the dark ink, whichever reads better on the fill; 0.187 is where the two contrast ratios cross.
      root.style.setProperty("--accent-ink", lum > 0.187 ? "10 12 16" : "255 255 255");
      root.style.setProperty("--accent-deep", Math.round(r * 0.62) + " " + Math.round(g * 0.62) + " " + Math.round(b * 0.62));
    } else {
      root.setAttribute("data-accent", "azure");
    }
  } catch (e) {}
})();
