// vite.config.ts
//
// Purpose
// -------
// Build/dev-server configuration for the Phase 3.7 frontend, plus its
// Vitest test configuration (kept in the same file -- Vitest reads a
// `test` block directly off the Vite config rather than requiring a
// second config file, per Vitest's own recommended setup).
//
// Why a dev-server proxy for `/api`
// ----------------------------------
// The frontend talks to the backend exclusively via relative URLs
// (`/api/v1/language/parse`, see `src/api/language.ts`) so the same
// built bundle works unmodified behind any reverse proxy in
// production. In local development there is no such proxy -- Vite's
// dev server (default port 5173) and FastAPI (default port 8000) are
// two separate processes -- so this config forwards `/api` and
// `/health` requests to the backend to keep that "always relative
// URLs" contract true in dev too, rather than making the frontend
// branch on environment to build an absolute URL.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND_URL = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": BACKEND_URL,
      "/health": BACKEND_URL,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
