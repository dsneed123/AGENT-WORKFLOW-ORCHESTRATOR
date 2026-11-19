import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The studio serves ui/dist from disk, so the build output is what the browser gets.
// `npm run dev` proxies the API to the running studio on 8740 instead; AWO_API=<url>
// points that proxy at a studio on another machine. The built bundle has no address
// in it at all — see docs/split-deploy.md.
declare const process: { env: Record<string, string | undefined> };
const api = process.env.AWO_API || "http://127.0.0.1:8740";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: true },
  server: {
    port: 8741,
    proxy: {
      "/api": { target: api, changeOrigin: true, ws: false },
      "/fonts": { target: api, changeOrigin: true },
    },
  },
});
