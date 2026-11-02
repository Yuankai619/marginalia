"""One-shot calls through `codex exec`, the optional second engine.

Codex's read-only sandbox still lets its tools read any file on the machine, and the prompt carries untrusted course
text, so Codex gets no tools at all: every tool feature is disabled and the material travels inside the prompt (plus
attached images). It runs in an empty temp dir with an allowlisted environment, without the user's config.toml, and
only with a ChatGPT subscription login: a CODEX_HOME holding an API-key login is refused before Codex starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

NO_TOOLS = (
    "shell_tool", "unified_exec", "code_mode_host", "view_image", "browser_use", "browser_use_external",
    "in_app_browser", "computer_use", "apps", "plugins", "remote_plugin", "skill_search", "tool_suggest", "memories",
    "goals",
)  # fmt: skip
ENV_KEEP = (
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
)  # fmt: skip


def _home(codex_home: Path | None) -> Path:
    return codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def login_problem(codex_home: Path | None = None) -> str | None:
    """Why this CODEX_HOME can't be used, or None when it holds a ChatGPT subscription login."""
    if shutil.which("codex") is None:
        return "找不到 codex 指令"
    try:
        auth = json.loads((_home(codex_home) / "auth.json").read_text("utf-8"))
    except (OSError, ValueError):
        return "Codex 沒有登入"
    if not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt" or auth.get("OPENAI_API_KEY"):
        return "Codex 不是用 ChatGPT 訂閱登入（API key 登入會產生 API 費用，不使用）"
    return None


def available(codex_home: Path | None = None) -> bool:
    return login_problem(codex_home) is None


def _env(codex_home: Path | None) -> dict[str, str]:
    return {**{k: os.environ[k] for k in ENV_KEEP if k in os.environ}, "CODEX_HOME": str(_home(codex_home))}


def _args(tmp: str, out: Path, model: str | None, images: list[Path]) -> list[str]:
    args = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--sandbox", "read-only"]
    args += ["--color", "never", "-C", tmp, "-o", str(out)]
    args += ["-c", 'forced_login_method="chatgpt"', "-c", 'web_search="disabled"', "-c", "mcp_servers={}"]
    for feature in NO_TOOLS:
        args += ["--disable", feature]
    if model:
        args += ["-m", model]
    for img in images:
        args += [f"--image={img}"]
    return [*args, "-"]  # prompt on stdin: no argv length limit, nothing visible in `ps`


async def complete(
    prompt: str,
    *,
    codex_home: Path | None = None,
    model: str | None = None,
    images: list[Path] | None = None,
    timeout: float = 600,
) -> str:
    """Run one prompt and return codex's final message."""
    if problem := login_problem(codex_home):
        raise RuntimeError(problem)
    with tempfile.TemporaryDirectory(prefix="marginalia-codex-") as tmp:
        out = Path(tmp) / "last.txt"
        proc = await asyncio.create_subprocess_exec(
            *_args(tmp, out, model, images or []),
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
