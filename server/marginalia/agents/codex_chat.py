"""Context-only Codex chat: no project config or filesystem-reading model tools."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import weakref
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..llm.accounts import subscription_auth
from ..llm.codex import account_home
from ..store import write_json


def _catalog(model: str) -> dict:
    # A local catalog prevents remote model metadata from adding native tools.
    return {
        "models": [
            {
                "slug": model,
                "display_name": model,
                "description": "Course chat",
                "base_instructions": "依提供的課程上下文以繁體中文回答。沒有工具，不要嘗試讀取檔案。",
                "supported_reasoning_levels": [],
                "shell_type": "disabled",
                "visibility": "list",
                "supported_in_api": True,
                "priority": 0,
                "support_verbosity": False,
                "apply_patch_tool_type": None,
                "truncation_policy": {"mode": "tokens", "limit": 10000},
                "experimental_supported_tools": [],
                "supports_search_tool": False,
                "include_apps_usage_instructions": False,
            }
        ]
    }


async def _drain(reader: asyncio.StreamReader) -> None:
    while await reader.read(65536):
        pass  # Diagnostics may include credentials; retain and expose none.


async def _stop(process: asyncio.subprocess.Process) -> None:
    def send(sig):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            else:
                process.send_signal(sig)
        except ProcessLookupError:
            pass

    # The session belongs only to this invocation, including launcher descendants.
    send(signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), 2)
    except TimeoutError:
        pass
    finally:
        send(signal.SIGKILL)
        await process.wait()


_account_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


async def stream(
    prompt: str,
    account: str,
    model: str,
    effort: str,
    image: Path | None = None,
) -> AsyncIterator[dict[str, Any]]:
    lock = _account_locks.setdefault(account, asyncio.Lock())
    async with lock:
        events = _stream(prompt, account, model, effort, image)
        try:
            async for event in events:
                yield event
        finally:
            await events.aclose()


async def _stream(
    prompt: str,
    account: str,
    model: str,
    effort: str,
    image: Path | None = None,
) -> AsyncIterator[dict[str, Any]]:
    home = account_home(account)
    auth = subscription_auth(home)
    if not auth:
        raise ValueError("指定的 Codex 帳號未以訂閱登入")
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("找不到 Codex")
    with tempfile.TemporaryDirectory(prefix="marginalia-chat-") as tmp:
        root = Path(tmp)
        # Copy only subscription credentials. No account config, MCP, hooks or skills.
        auth_path = root / "auth.json"
        auth_path.touch(mode=0o600)
        auth_path.write_text(json.dumps(auth), encoding="utf-8")
        catalog = root / "models.json"
        catalog.write_text(json.dumps(_catalog(model)), encoding="utf-8")
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "OPENAI_API_KEY",
                "CODEX_API_KEY",
                "OPENAI_BASE_URL",
                "CODEX_HOME",
                "CODEX_MANAGED_CONFIG_FILE",
                "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
            }
        }
        env.update(CODEX_HOME=tmp, HOME=tmp)
        args = [
            binary,
            "exec",
            "--json",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "-C",
            tmp,
            "-m",
            model,
        ]
        settings = {
            "model_provider": '"openai"',
            "forced_login_method": '"chatgpt"',
            "model_catalog_json": json.dumps(str(catalog)),
            "model_reasoning_effort": json.dumps(effort),
            "web_search": '"disabled"',
            "mcp_servers": "{}",
            "agents.enabled": "false",
            "skills.include_instructions": "false",
            "tools.update_plan.enabled": "false",
            "tools.experimental_request_user_input.enabled": "false",
        }
        for feature in (
            "shell_tool",
            "view_image",
            "multi_agent",
            "multi_agent_v2",
            "apps",
            "plugins",
            "hooks",
            "code_mode",
            "code_mode_only",
            "browser_use",
            "computer_use",
            "image_generation",
            "memories",
            "skill_search",
            "tool_suggest",
            "goals",
            "sleep_tool",
        ):
            settings[f"features.{feature}"] = "false"
        for key, value in settings.items():
            args.extend(["-c", f"{key}={value}"])
        if image:
            args.append(f"--image={image}")
        args.append("-")
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=os.name == "posix",
            limit=4 * 1024 * 1024,
        )
        assert process.stdout and process.stderr and process.stdin
        stderr = asyncio.create_task(_drain(process.stderr))

        async def send_prompt():
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

        sender = asyncio.create_task(send_prompt())
        try:
            async for raw in process.stdout:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                item = event.get("item", {})
                if (
                    event.get("type") == "item.completed"
                    and item.get("type") == "agent_message"
                ):
                    text = item.get("text")
                    if isinstance(text, str):
                        yield {"type": "text", "delta": text}
                elif event.get("type") in {"error", "turn.failed"}:
                    raise RuntimeError("Codex 執行失敗")
            await sender
            if await process.wait():
                raise RuntimeError("Codex 執行失敗")
            yield {"type": "done"}
        finally:
            await _stop(process)
            sender.cancel()
            stderr.cancel()
            await asyncio.gather(sender, stderr, return_exceptions=True)
            refreshed = subscription_auth(root)
            if refreshed and refreshed != auth and subscription_auth(home) == auth:
                # Preserve CLI token rotation without replacing a newer external login.
                write_json(home / "auth.json", refreshed)
