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
  build: {
    // Keep the long-lived vendor code in its own cacheable chunk.
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
          icons: ["lucide-react"],
        },
      },
    },
  },
});
