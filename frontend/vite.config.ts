import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    // Reachable from the sandbox preview host, not just loopback.
    host: "0.0.0.0",
    port: 5173,
    // Dev-only: allow tunnel/preview hostnames (e.g. *.e2b.app) through Vite's
    // host check. Never relevant to a production build.
    allowedHosts: true,
    // Same-origin `/api/*` in development: no CORS, no hardcoded host.
    proxy: {
      "/api": {
        target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        // SSE must not be buffered by the dev proxy.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              delete proxyRes.headers["content-length"];
            }
          });
        },
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
  },
}));
