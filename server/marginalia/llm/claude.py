"""One-shot and streaming calls through the user's local Claude Code login.

claude-agent-sdk spawns the Claude Code CLI, which bills the logged-in
subscription. We drop ANTHROPIC_API_KEY from the child environment so a key
lying around in the shell can never switch billing to the API.
"""

from __future__ import annotations

import base64
import os
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from ..course_access import check_tree, confined


@dataclass
class Call:
    prompt: str
    system: str = ""
    images: list[Path] = field(default_factory=list)
    model: str = "sonnet"
    effort: str | None = None
    cwd: Path | None = None
    tools: list[str] = field(
        default_factory=list
    )  # e.g. ["Read", "Grep"] for read-only course access
    max_turns: int = 1
    read_root: Path | None = None


def _env() -> dict[str, str]:
    # blank everything that could move billing or traffic off the subscription login
    blank = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
    return {**dict.fromkeys(blank, ""), "CLAUDE_CODE_ENTRYPOINT": "marginalia"}


def _read_target(root: Path, name: str, data: dict) -> None:
    if name not in {"Read", "Grep", "Glob"}:
        raise ValueError("不允許的工具")
    value = data.get("file_path") if name == "Read" else data.get("path", ".")
    if not isinstance(value, str) or not value:
        raise ValueError("缺少讀取路徑")
    path = confined(root / Path(value).expanduser(), root)
    if name in {"Grep", "Glob"}:
        pattern = data.get("pattern" if name == "Glob" else "glob", "")
        if (
            not isinstance(pattern, str)
            or ".." in Path(pattern).parts
            or Path(pattern).is_absolute()
        ):
            raise ValueError("搜尋範圍不正確")
        check_tree(path, root)


def _options(c: Call) -> ClaudeAgentOptions:
    opts = {
        "system_prompt": c.system or None,
        "model": c.model,
        "cwd": str(c.cwd) if c.cwd else None,
        "tools": c.tools,
        "allowed_tools": [] if c.read_root else c.tools,
        "disallowed_tools": [
            "Bash",
            "Write",
            "Edit",
            "MultiEdit",
            "NotebookEdit",
            "WebFetch",
            "WebSearch",
            "Task",
            "Agent",
        ],
        "permission_mode": "default",
        "max_turns": c.max_turns,
        "env": _env(),
        "setting_sources": [],  # don't pick up the user's CLAUDE.md / hooks
    }
    if c.read_root:

        async def permission(name, data, context):
            del context
            try:
                _read_target(c.read_root, name, data)
            except (ValueError, TypeError):
                return PermissionResultDeny(message="只允許讀取這門課的資料")
            return PermissionResultAllow()

        async def before_tool(data, tool_use_id, context):
            result = await permission(data["tool_name"], data["tool_input"], context)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": result.behavior,
                    "permissionDecisionReason": "課程資料讀取邊界",
                }
            }

        opts["can_use_tool"] = permission
        opts["hooks"] = {"PreToolUse": [HookMatcher(hooks=[before_tool])]}
    if c.effort:
        opts["extra_args"] = {"effort": c.effort}
    return ClaudeAgentOptions(**{k: v for k, v in opts.items() if v is not None})


async def _messages(c: Call):
    content: list[dict] = []
    for p in c.images:
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }[p.suffix.lower()]
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(p.read_bytes()).decode(),
                },
            }
        )
    content.append({"type": "text", "text": c.prompt})
    yield {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


async def stream(c: Call) -> AsyncIterator[dict]:
    """Yields {"type":"text","delta"} / {"type":"tool","title","detail"} / {"type":"done","usage"}."""
    prompt = _messages(c) if c.images else c.prompt
    with tempfile.TemporaryDirectory(prefix="marginalia-claude-") as tmp:  # 0700: not readable by other users
        opts = _options(c)
        if c.system:
            # chat system prompts carry the course outline and can pass the 128 KiB argv limit; a file also keeps
            # transcripts and notes out of `ps`
            path = Path(tmp) / "system.md"
            path.write_text(c.system, "utf-8")
            opts.system_prompt = {"type": "file", "path": str(path)}
        async for event in _events(prompt, opts):
            yield event


async def _events(prompt, opts: ClaudeAgentOptions) -> AsyncIterator[dict]:
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    yield {"type": "text", "delta": b.text}
                elif isinstance(b, ToolUseBlock):
                    detail = b.input.get("file_path") or b.input.get("pattern") or ""
                    yield {
                        "type": "tool",
                        "title": b.name,
                        "detail": os.path.basename(str(detail)) if detail else "",
                    }
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                raise RuntimeError(msg.result or "Claude 回傳錯誤")
            yield {"type": "done", "usage": msg.usage, "cost": msg.total_cost_usd}


async def complete(c: Call) -> str:
    parts = [e["delta"] async for e in stream(c) if e["type"] == "text"]
    return "".join(parts).strip()
