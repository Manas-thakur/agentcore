import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build lands inside the Python package, so installing it
// (`pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"`) ships the web
// app with no Node.js needed. FastAPI serves index.html at "/" (with an SPA fallback for the
// app's routes) and the hashed assets under /static/.
const API = process.env.AGENTCORE_URL || "http://127.0.0.1:8761";

export default defineConfig({
  base: "/static/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: path.resolve(__dirname, "../src/agentcore/server/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 8762,
    strictPort: true,
    proxy: Object.fromEntries(
      ["/api", "/v1", "/health", "/metrics", "/docs", "/openapi.json"].map((p) => [p, { target: API, changeOrigin: true }]),
    ),
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
