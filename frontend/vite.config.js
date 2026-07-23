import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + media calls to the Django backend so the SPA can
// use relative URLs. Change the target if your backend runs elsewhere.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/media": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
