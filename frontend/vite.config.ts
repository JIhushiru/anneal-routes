import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Point the dev proxy elsewhere with BACKEND_URL (e.g. docker-compose, or a
// non-default local port): BACKEND_URL=http://localhost:8001 npm run dev
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
