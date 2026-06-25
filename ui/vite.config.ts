import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config — UI only. API is served by Express in server.ts.
// In dev: vite proxies /api/* to the express server on :3012.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3012,
    proxy: {
      "/api": "http://localhost:3012",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});