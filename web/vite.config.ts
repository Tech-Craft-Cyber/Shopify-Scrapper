import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately (python manage.py serve); Vite proxies /api to it.
const API = process.env.API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": API } },
  build: { outDir: "dist", sourcemap: false },
});
