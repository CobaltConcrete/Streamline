import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// D-6: served by the FastAPI backend on 127.0.0.1 in production (dist/).
// In dev, proxy API/WS calls to the backend so the app can run against
// `vite dev` with hot reload instead of a full rebuild each time.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8756",
      "/ws": {
        target: "ws://127.0.0.1:8756",
        ws: true,
      },
    },
  },
});
