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

for (const scenario of ["missing-courses", "empty-courses", "no-registered-courses", "missing-uv", "export-success", "export-failed", "frontend-failed"]) {
  test(`build handles ${scenario} without masking other failures`, () => {
    const root = mkdtempSync(join(tmpdir(), "marginalia-build-fallback-"));
    for (const directory of ["scripts", "server", "bin"]) mkdirSync(join(root, directory));
    copyFileSync(new URL("./build.mjs", import.meta.url), join(root, "scripts/build.mjs"));
    const courses = join(root, "courses");
    if (scenario !== "missing-courses") mkdirSync(courses);
    if (scenario === "no-registered-courses") {
      mkdirSync(join(courses, ".private"));
      writeFileSync(join(courses, ".private/course.json"), "{}");
      mkdirSync(join(courses, "unrelated"));
      writeFileSync(join(courses, "README.md"), "No courses here");
    }
    if (["missing-uv", "export-success", "export-failed", "frontend-failed"].includes(scenario)) {
      mkdirSync(join(courses, "fixture"));
      writeFileSync(join(courses, "fixture/course.json"), "{}");
    }
    writeFileSync(join(root, "bin/pnpm"), `#!${process.execPath}
const fs = require('node:fs');
if (process.env.SCENARIO === 'frontend-failed') process.exit(5);
fs.mkdirSync('apps/web/dist/assets', {recursive:true});
fs.writeFileSync('apps/web/dist/index.html', '<html>Generated frontend</html>');
fs.writeFileSync('apps/web/dist/assets/app.js', '// Generated frontend asset');
`, { mode: 0o755 });
    // No uv executable exists for missing-uv, even if it is installed on the test host.
    if (scenario !== "missing-uv") {
      writeFileSync(join(root, "bin/uv"), `#!${process.execPath}
const fs = require('node:fs');
fs.writeFileSync('../export-started', 'yes');
if (process.env.SCENARIO === 'export-success') {
  fs.mkdirSync('../apps/web/dist/data', {recursive:true});
  fs.writeFileSync('../apps/web/dist/data/courses.json', '[{"id":"fixture"}]');
} else process.exit(7);
`, { mode: 0o755 });
    }
    const result = spawnSync(process.execPath, [join(root, "scripts/build.mjs")], {
      encoding: "utf8",
      env: { ...process.env, PATH: join(root, "bin"), MARGINALIA_COURSES: courses,
        MARGINALIA_EXPORT_COURSES: "", SCENARIO: scenario },
    });
    if (["export-failed", "frontend-failed"].includes(scenario)) {
      assert.equal(result.status, scenario === "export-failed" ? 7 : 5);
      assert.doesNotMatch(result.stderr, /Skipping course export/);
      assert.equal(existsSync(join(root, "apps/web/dist/data/courses.json")), false);
    } else if (scenario === "export-success") {
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.stderr, "");
      assert.equal(readFileSync(join(root, "apps/web/dist/data/courses.json"), "utf8"), '[{"id":"fixture"}]');
    } else {
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stderr, scenario === "missing-uv" ? /uv is not installed or not on PATH/ : /no courses found/);
      assert.equal(result.stderr.trim().split("\n").length, 1);
      assert.match(result.stderr, /^Warning: [\x20-\x7e]+\n$/);
      assert.equal(readFileSync(join(root, "apps/web/dist/data/courses.json"), "utf8"), "[]\n");
      assert.equal(readFileSync(join(root, "apps/web/dist/404.html"), "utf8"), '<html>Generated frontend</html>');
      assert.equal(existsSync(join(root, "apps/web/dist/assets/app.js")), true);
    }
    assert.equal(existsSync(join(root, "export-started")), ["export-failed", "export-success"].includes(scenario));
  });
}
