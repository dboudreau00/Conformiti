import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Not CONFORMITI_API_PORT, which moves the Docker stack's API publish: a value exported for Docker must never
// point the local app at the Docker backend and its database.
const API_PORT = process.env.E2E_API_PORT || process.env.CONFORMITI_DEV_API_PORT || 8000;
const API_TARGET = `http://127.0.0.1:${API_PORT}`;
const proxy = {
  "/api": { target: API_TARGET, changeOrigin: true },
  "/media": { target: API_TARGET, changeOrigin: true },
};

const VENDOR = [
  ["react", ["react", "react-dom", "react-router-dom"]],
  ["motion", ["framer-motion"]],
  ["icons", ["lucide-react"]],
  ["pdf", ["pdfjs-dist"]],
];

// A function, not the object form: Vite's Rolldown bundler accepts only a function here.
function manualChunks(id) {
  const path = id.split("\\").join("/");
  if (!path.includes("/node_modules/")) return undefined;
  for (const [chunk, packages] of VENDOR) {
    if (packages.some((name) => path.includes("/node_modules/" + name + "/"))) return chunk;
  }
  return undefined;
}

// strictPort: sign-in is refused from any origin missing from CSRF_TRUSTED_ORIGINS (.env.example allows 5173),
// so a busy port must fail, not move; a new port needs its origin in CSRF_TRUSTED_ORIGINS and CORS_ALLOWED_ORIGINS.
const DEV_PORT = Number(process.env.CONFORMITI_DEV_PORT) || 5173;

// The pages are imported eagerly, so the app's own chunk passes Vite's 500 kB default by design;
// 700 kB still warns if a large dependency lands in it by accident.
const CHUNK_WARNING_KB = 700;

export default defineConfig({
  plugins: [react()],
  server: { port: DEV_PORT, strictPort: true, proxy },
  preview: { port: 4173, proxy },
  build: { chunkSizeWarningLimit: CHUNK_WARNING_KB, rollupOptions: { output: { manualChunks } } },
});
