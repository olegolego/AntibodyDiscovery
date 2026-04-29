import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// When started via start.sh on a network host, VITE_API_HOST is set to
// http://<host-ip>:8000 so the browser (on another machine) can reach the backend.
// Falls back to localhost for single-machine dev.
const backendHttp = process.env.VITE_API_HOST ?? "http://localhost:8000";
const backendWs   = backendHttp.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendHttp,
        changeOrigin: true,
      },
      "/papers": {
        target: backendHttp,
        changeOrigin: true,
      },
      "/ws": {
        target: backendWs,
        ws: true,
      },
    },
  },
});
