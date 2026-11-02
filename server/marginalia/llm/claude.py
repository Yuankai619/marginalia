"""One-shot and streaming calls through the user's local Claude Code login.

claude-agent-sdk spawns the Claude Code CLI, which bills the logged-in
subscription. We drop ANTHROPIC_API_KEY from the child environment so a key
lying around in the shell can never switch billing to the API.
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock, query


@dataclass
class Call:
    prompt: str
    system: str = ""
    images: list[Path] = field(default_factory=list)
    model: str = "sonnet"
    effort: str | None = None
    cwd: Path | None = None
    tools: list[str] = field(default_factory=list)  # e.g. ["Read", "Grep"] for read-only course access
    max_turns: int = 1


def _env() -> dict[str, str]:
    return {"ANTHROPIC_API_KEY": "", "CLAUDE_CODE_ENTRYPOINT": "marginalia"}


def _options(c: Call) -> ClaudeAgentOptions:
    opts = dict(
        system_prompt=c.system or None,
        model=c.model,
        cwd=str(c.cwd) if c.cwd else None,
        allowed_tools=c.tools,
        disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task"],
        permission_mode="default",
        max_turns=c.max_turns,
        env=_env(),
        setting_sources=[],  # don't pick up the user's CLAUDE.md / hooks
    )
    if c.effort:
        opts["extra_args"] = {"effort": c.effort}
    return ClaudeAgentOptions(**{k: v for k, v in opts.items() if v is not None})


async def _messages(c: Call):
    content: list[dict] = []
    for p in c.images:
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[p.suffix.lower()]
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(p.read_bytes()).decode()}})
    content.append({"type": "text", "text": c.prompt})
    yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}


async def stream(c: Call) -> AsyncIterator[dict]:
    """Yields {"type":"text","delta"} / {"type":"tool","title","detail"} / {"type":"done","usage"}."""
    prompt = _messages(c) if c.images else c.prompt
    async for msg in query(prompt=prompt, options=_options(c)):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    yield {"type": "text", "delta": b.text}
                elif isinstance(b, ToolUseBlock):
                    detail = b.input.get("file_path") or b.input.get("pattern") or ""
                    yield {"type": "tool", "title": b.name, "detail": os.path.basename(str(detail)) if detail else ""}
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                raise RuntimeError(msg.result or "Claude 回傳錯誤")
            yield {"type": "done", "usage": msg.usage, "cost": msg.total_cost_usd}


async def complete(c: Call) -> str:
    parts = [e["delta"] async for e in stream(c) if e["type"] == "text"]
    return "".join(parts).strip()
