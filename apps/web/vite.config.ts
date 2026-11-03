import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// MARGINALIA_API lets a second checkout run against its own backend (default: the `pnpm dev` one on :8765).
const api = process.env.MARGINALIA_API || "http://127.0.0.1:8765";

// The static build is a public site that renders model-written notes, so it ships a CSP as a second line of
// defence: no remote images, scripts or fetches; videos may come from the course's public video URLs.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' blob: https:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'none'",
].join("; ");

// `pnpm dev` (chat and editing happen here) gets the part that stops data leaving: no remote images or fetches.
// Scripts stay unrestricted because Vite's dev server injects inline modules.
const DEV_CSP = "img-src 'self' data: blob:; connect-src 'self' ws: wss:";

const staticCsp: Plugin = {
  name: "marginalia-static-csp",
  apply: "build",
  transformIndexHtml: (html) =>
    html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`),
};

export default defineConfig({
  base: process.env.VITE_BASE_PATH || "/",
  plugins: [react(), tailwindcss(), staticCsp],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    headers: { "Content-Security-Policy": DEV_CSP },
    proxy: {
      "/api": { target: api, changeOrigin: true },
      "/files": { target: api, changeOrigin: true },
    },
  },
});
