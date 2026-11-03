import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { preview } from "vite";

const web = fileURLToPath(new URL("../", import.meta.url));
const image = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>';

for (const base of ["/", "/marginalia/"]) {
  for (const backendAvailable of [false, true]) {
    test(`preview serves only the snapshot at ${base} with backend ${backendAvailable ? "online" : "offline"}`, async () => {
      const dist = mkdtempSync(join(tmpdir(), "marginalia-preview-"));
      const asset = "files/fixture/notes/deck/assets/diagram.svg";
      mkdirSync(join(dist, "files/fixture/notes/deck/assets"), { recursive: true });
      writeFileSync(join(dist, asset), image);
      writeFileSync(join(dist, "index.html"), "<html>Generated static reader</html>");
      const forwarded = [];
      const backend = createServer((request, response) => {
        forwarded.push(request.url);
        response.setHeader("Content-Type", "application/json");
        response.end('{"private":"not exported"}');
      });
      await new Promise(resolve => backend.listen(0, "127.0.0.1", resolve));
      const target = `http://127.0.0.1:${backend.address().port}`;
      if (!backendAvailable) await new Promise(resolve => backend.close(resolve));
      const previous = process.env.MARGINALIA_API;
      process.env.MARGINALIA_API = target;
      let site;
      try {
        site = await preview({
          root: web,
          configFile: join(web, "vite.config.ts"),
          base,
          build: { outDir: dist },
          preview: { host: "127.0.0.1", port: 0, strictPort: true, open: false },
          logLevel: "silent",
        });
        const origin = `http://127.0.0.1:${site.httpServer.address().port}`;
        const response = await fetch(`${origin}${base}${asset}`);
        assert.equal(response.status, 200);
        assert.match(response.headers.get("content-type"), /image\/svg\+xml/);
        assert.equal(await response.text(), image);
        for (const path of new Set(["/api/health", `${base}api/health`, `${base}files/unexported/course.json`])) {
          const missing = await fetch(`${origin}${path}`, { headers: { Accept: "application/json" } });
          assert.equal(missing.status, 404, path);
        }
        assert.deepEqual(forwarded, []);
        assert.deepEqual(site.config.preview.proxy, {});
        assert.equal(site.config.server.proxy["/api"].target, target);
        assert.equal(site.config.server.proxy["/files"].changeOrigin, true);
      } finally {
        if (site) await site.close();
        if (backendAvailable) await new Promise(resolve => backend.close(resolve));
        if (previous === undefined) delete process.env.MARGINALIA_API;
        else process.env.MARGINALIA_API = previous;
      }
    });
  }
}
