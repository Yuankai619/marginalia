import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

for (const scenario of ["inside", "ancestor", "symlink"]) {
  test(`build rejects ${scenario} source/output overlap before starting Vite`, () => {
    const root = mkdtempSync(join(tmpdir(), "marginalia-build-test-"));
    mkdirSync(join(root, "scripts"));
    mkdirSync(join(root, "apps/web/dist/course"), { recursive: true });
    copyFileSync(new URL("./build.mjs", import.meta.url), join(root, "scripts/build.mjs"));
    const sentinel = join(root, "apps/web/dist/course/course.json");
    writeFileSync(sentinel, '{"title":"generated fixture"}');
    const courseRoot = scenario === "ancestor" ? root : join(root, "apps/web/dist/course");
    if (scenario === "symlink") symlinkSync(courseRoot, join(root, "alias"));
    // If the guard fails, the fake package manager records that it was invoked.
    mkdirSync(join(root, "bin"));
    const marker = join(root, "build-started");
    writeFileSync(join(root, "bin/pnpm"), '#!/bin/sh\ntouch "$BUILD_MARKER"\nexit 3\n', { mode: 0o755 });
    const result = spawnSync(process.execPath, [join(root, "scripts/build.mjs")], {
      encoding: "utf8",
      env: { ...process.env, PATH: `${join(root, "bin")}:${process.env.PATH}`, BUILD_MARKER: marker,
        MARGINALIA_COURSES: scenario === "symlink" ? join(root, "alias") : courseRoot },
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /來源重疊/);
    assert.equal(existsSync(marker), false);
    assert.equal(readFileSync(sentinel, "utf8"), '{"title":"generated fixture"}');
  });
}
