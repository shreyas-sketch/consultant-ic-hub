import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// Two bundles: the consultant app (index.html) and the small client bundle
// (client.html) for lead forms, booking pages, client files and the portal.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: { app: resolve(__dirname, "index.html"), client: resolve(__dirname, "client.html") },
    },
    chunkSizeWarningLimit: 900,
  },
  server: { proxy: { "/api": "http://localhost:8765", "/mcp": "http://localhost:8765" } },
});
