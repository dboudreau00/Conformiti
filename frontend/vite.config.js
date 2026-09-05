import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + media calls to the Django backend so the SPA can
// use relative URLs. Change the target if your backend runs elsewhere.
// `vite preview` gets the same proxy so the end-to-end suite (e2e/) can drive
// the *built* bundle rather than the dev server; E2E_API_PORT points it at the
// throwaway backend the suite starts.
const API_TARGET = `http://127.0.0.1:${process.env.E2E_API_PORT || 8000}`;
const proxy = {
  "/api": { target: API_TARGET, changeOrigin: true },
  "/media": { target: API_TARGET, changeOrigin: true },
};

// Long-lived vendor code gets its own cacheable chunks. Written as a function
// rather than the object form because Vite's Rolldown bundler accepts only a
// function here.
const VENDOR = [
  ["react", ["react", "react-dom", "react-router-dom"]],
  ["motion", ["framer-motion"]],
  ["icons", ["lucide-react"]],
  ["pdf", ["pdfjs-dist"]],
];

function manualChunks(id) {
  const path = id.split("\\").join("/");
  if (!path.includes("/node_modules/")) return undefined;
  for (const [chunk, packages] of VENDOR) {
    if (packages.some((name) => path.includes("/node_modules/" + name + "/"))) return chunk;
  }
  return undefined;
}

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
  build: { rollupOptions: { output: { manualChunks } } },
});
