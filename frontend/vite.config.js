import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + media calls to the Django backend so the SPA can
// use relative URLs. The backend is expected on 127.0.0.1 at
// CONFORMITI_DEV_API_PORT (default 8000), the port the local runserver
// listens on. It is deliberately not CONFORMITI_API_PORT, which moves only the
// Docker stack's API publish: a value exported for Docker must never point the
// local web app at the Docker backend and its database. Read from the shell
// environment: Vite does not load the repository's .env into this file.
// `vite preview` gets the same proxy so the end-to-end suite (e2e/) can drive
// the *built* bundle rather than the dev server; E2E_API_PORT points it at the
// throwaway backend the suite starts, and wins over CONFORMITI_DEV_API_PORT.
const API_PORT = process.env.E2E_API_PORT || process.env.CONFORMITI_DEV_API_PORT || 8000;
const API_TARGET = `http://127.0.0.1:${API_PORT}`;
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

// The dev server's own port: CONFORMITI_DEV_PORT, default 5173 (never
// CONFORMITI_PORT, which is the Docker stack's nginx). strictPort
// makes a busy port an error instead of a quiet move to the next one, because
// the API refuses sign-in from any origin missing from CSRF_TRUSTED_ORIGINS
// (.env.example sets http://localhost:5173). Moving the port means adding
// its origin to CSRF_TRUSTED_ORIGINS and CORS_ALLOWED_ORIGINS in .env too.
const DEV_PORT = Number(process.env.CONFORMITI_DEV_PORT) || 5173;

export default defineConfig({
  plugins: [react()],
  server: { port: DEV_PORT, strictPort: true, proxy },
  preview: { port: 4173, proxy },
  build: { rollupOptions: { output: { manualChunks } } },
});
