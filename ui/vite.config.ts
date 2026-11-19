import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The studio serves ui/dist from disk, so the build output is what the browser gets.
// `npm run dev` proxies the API to the running studio on 8740 instead.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
  server: {
    port: 8741,
    proxy: {
      "/api": { target: "http://127.0.0.1:8740", changeOrigin: true, ws: false },
      "/fonts": { target: "http://127.0.0.1:8740", changeOrigin: true },
    },
  },
});
