import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Keep the browser host for Django's same-origin CSRF validation.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
      "/admin": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { chunkSizeWarningLimit: 5000 },
});
