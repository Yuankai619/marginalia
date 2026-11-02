import { spawn } from "node:child_process";

const processes = [];
const start = (command, args, cwd = process.cwd()) => {
  const child = spawn(command, args, {
    stdio: "inherit",
    shell: process.platform === "win32",
    cwd,
  });
  processes.push(child);
  child.on("exit", (code) => {
    if (code && code !== 0) console.warn(`${command} exited with ${code}; Vite remains available.`);
  });
};

start("uv", ["run", "uvicorn", "marginalia.api:app", "--port", "8765"], "server");
start("pnpm", ["--filter", "@marginalia/web", "dev"]);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    for (const child of processes) child.kill(signal);
    process.exit();
  });
}
