import { copyFileSync, existsSync, realpathSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit", env: process.env });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

// Resolve existing ancestors too, so an output/source symlink cannot hide an overlap.
function canonical(path) {
  return existsSync(path) ? realpathSync(path) : join(canonical(dirname(path)), basename(path));
}
function contains(parent, child) {
  const path = relative(parent, child);
  return path === "" || (path !== ".." && !path.startsWith(`..${sep}`) && !isAbsolute(path));
}
const coursesRoot = resolve(root, process.env.MARGINALIA_COURSES ||
  join(process.env.MARGINALIA_ROOT || root, "courses"));
const source = canonical(coursesRoot);
const destination = canonical(join(root, "apps/web/dist"));
if (contains(source, destination) || contains(destination, source)) {
  console.error("匯出目錄不能與課程來源重疊；尚未執行 build，課程資料未變更");
  process.exit(1);
}
process.env.MARGINALIA_COURSES = coursesRoot;

// Vite clears dist first; export then writes the complete public snapshot alongside its assets.
run("pnpm", ["--filter", "@marginalia/web", "build"]);
copyFileSync(`${root}apps/web/dist/index.html`, `${root}apps/web/dist/404.html`);
const courses = (process.env.MARGINALIA_EXPORT_COURSES || "").split(",").map(s => s.trim()).filter(Boolean);
run("uv", ["run", "marginalia", "export", ...courses, "--out", `${root}apps/web/dist`], `${root}server`);
