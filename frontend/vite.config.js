import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const root = dirname(fileURLToPath(import.meta.url));

// Two bundles: the consultant app (index.html) and the small client bundle
// (client.html) for lead forms, booking pages, client files and the portal.
// Both are served by the backend from the same origin, so cookies just work.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": resolve(root, "src") } },
  build: {
    rollupOptions: {
      input: { app: resolve(root, "index.html"), client: resolve(root, "client.html") },
      output: {
        // Long-lived vendor chunks: a deploy that only changes app code keeps these cached.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/.test(id)) return "vendor-react";
          if (id.includes("@tanstack")) return "vendor-query";
          if (id.includes("@tiptap") || id.includes("prosemirror")) return "vendor-editor";
          if (id.includes("@dnd-kit")) return "vendor-dnd";
          return undefined;
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
  server: { proxy: { "/api": "http://localhost:8765", "/mcp": "http://localhost:8765", "/.well-known": "http://localhost:8765" } },
});
