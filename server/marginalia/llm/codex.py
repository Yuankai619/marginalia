"""One-shot calls through `codex exec`, the optional second engine.

Uses whichever Codex login lives in the given CODEX_HOME. OPENAI_API_KEY is dropped from the child environment so a
key in the shell can never switch billing to the API. The sandbox is read-only, the session is not persisted, and
the user's config.toml (MCP servers, hooks) is not loaded.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path


def available(codex_home: Path | None = None) -> bool:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return shutil.which("codex") is not None and (home / "auth.json").exists()


def _env(codex_home: Path | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL")}
    if codex_home:
        env["CODEX_HOME"] = str(codex_home)
    return env


async def complete(
    prompt: str,
    *,
    codex_home: Path | None = None,
    model: str | None = None,
    images: list[Path] | None = None,
    cwd: Path | None = None,
    timeout: float = 600,
) -> str:
    """Run one prompt and return codex's final message."""
    with tempfile.TemporaryDirectory(prefix="marginalia-codex-") as tmp:
        out = Path(tmp) / "last.txt"
        args = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--sandbox", "read-only"]
        args += ["--color", "never"]
        args += ["-C", str(cwd or tmp), "-o", str(out)]
        if model:
            args += ["-m", model]
        for img in images or []:
            args += [f"--image={img}"]
        args.append("-")  # prompt on stdin: no argv length limit, nothing visible in `ps`
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=_env(codex_home),
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
        except TimeoutError:
            raise RuntimeError("Codex 逾時") from None
        finally:
            if proc.returncode is None:  # timed out or the job was cancelled
                proc.kill()
                await proc.wait()
        if proc.returncode != 0:
            tail = err.decode(errors="replace").strip().splitlines()[-1:] or [""]
            raise RuntimeError(f"Codex 執行失敗（{proc.returncode}）：{tail[0][:200]}")
        return out.read_text("utf-8").strip() if out.exists() else ""
