"""One-shot calls through `codex exec`, the optional second engine.

Codex's read-only sandbox still lets its tools read any file on the machine, and the prompt carries untrusted course
text, so Codex runs with every tool source turned off and the material travels inside the prompt (plus attached
images). The CLI (0.165) still declares two tools nothing can remove: `exec`, whose code-mode host is disabled so every
call fails, and `wait`, which only waits on exec. Before every call we render the model-visible tool list offline
(`codex debug prompt-input`, no model call, about a second) with the same flags and the same resolved executable, and
refuse to run if that check fails or lists anything else, or if the executable changed in between. A CLI upgrade that
adds a tool therefore fails closed. It runs in an empty temp dir with an allowlisted environment, without the
user's config.toml, and only with a ChatGPT subscription login: an API-key login is refused before Codex starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

NO_TOOLS = (
    "shell_tool", "unified_exec", "code_mode_host", "code_mode", "view_image", "browser_use", "browser_use_external",
    "in_app_browser", "computer_use", "apps", "plugins", "remote_plugin", "skill_search", "tool_suggest", "memories",
    "goals", "multi_agent", "multi_agent_v2", "image_generation", "sleep_tool",
)  # fmt: skip
CONFIG = (
    'forced_login_method="chatgpt"', 'web_search="disabled"', "mcp_servers={}", "agents.enabled=false",
    "tools.experimental_request_user_input.enabled=false", "tools.update_plan.enabled=false",
)  # fmt: skip
INERT_TOOLS = {"functions.exec", "functions.wait"}  # exec's host is disabled by code_mode_host above
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


def _lockdown() -> list[str]:
    args = [a for c in CONFIG for a in ("-c", c)]
    for feature in NO_TOOLS:
        args += ["--disable", feature]
    return args


def tool_names(prompt_input: list) -> list[str]:
    """Model-visible tool names from `codex debug prompt-input` output."""

    def walk(tools: list, prefix: str = "") -> list[str]:
        out = []
        for t in tools:
            name = f"{prefix}{t.get('name') or t.get('type')}"
            out += walk(t["tools"], f"{name}.") if t.get("tools") else [name]
        return out

    return [n for item in prompt_input if item.get("type") == "additional_tools" for n in walk(item.get("tools", []))]


def executable() -> tuple[str, tuple]:
    """The codex binary PATH resolves to, followed through links, and its file identity."""
    found = shutil.which("codex")
    if found is None:
        raise RuntimeError("找不到 codex 指令")
    real = os.path.realpath(found)
    return real, _identity(real)


def _identity(path: str) -> tuple:
    st = os.stat(path)
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


async def verify_tools(exe: str) -> None:
    """Fail closed unless `exe` would show the model only the inert tools. Offline: renders the prompt, calls no
    model. Runs against an empty CODEX_HOME, i.e. defaults plus our flags, which is what `exec --ignore-user-config`
    gets. Not cached: a long-running server may see the CLI upgraded underneath it."""
    with tempfile.TemporaryDirectory(prefix="marginalia-codex-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        proc = await asyncio.create_subprocess_exec(
            exe, "debug", "prompt-input", *_lockdown(), "x",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, cwd=tmp, env=_env(home),
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 60)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Codex 工具清單檢查失敗（結束碼 {proc.returncode}），不使用 Codex")
    try:
        names = tool_names(json.loads(out))
    except (ValueError, AttributeError, TypeError):
        raise RuntimeError("無法確認 Codex 的工具清單，不使用 Codex") from None
    if not names or set(names) - INERT_TOOLS:  # empty means the CLI stopped listing tools here: can't verify
        raise RuntimeError(f"Codex 會拿到工具 {', '.join(sorted(set(names) - INERT_TOOLS)) or '（無法確認）'}，不使用 Codex")


def _args(exe: str, tmp: str, out: Path, model: str | None, images: list[Path]) -> list[str]:
    args = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--sandbox", "read-only"]
    args += ["--color", "never", "-C", tmp, "-o", str(out), *_lockdown()]
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
    exe, identity = executable()
    await verify_tools(exe)
    if _identity(exe) != identity:
        raise RuntimeError("Codex 執行檔在檢查期間被換掉，不使用 Codex")
    with tempfile.TemporaryDirectory(prefix="marginalia-codex-") as tmp:
        out = Path(tmp) / "last.txt"
        proc = await asyncio.create_subprocess_exec(
            *_args(exe, tmp, out, model, images or []),
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
