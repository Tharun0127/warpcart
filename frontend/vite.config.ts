import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to the API on 8001 so the browser sees one origin
// (no CORS). In Docker, nginx does the same job (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5171,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
