import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only proxy target; in production FastAPI serves the built SPA same-origin.
const BACKEND = "http://localhost:8100";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3100,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
    },
  },
});
