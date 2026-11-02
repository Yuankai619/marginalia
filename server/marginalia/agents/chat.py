"""Read-only course chat backed by the locally logged-in Claude or Codex CLI."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
import weakref
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from ..course_access import check_course
from ..llm import claude
from ..store import Course, read_json, write_json
from . import codex_chat
from .prompts import MODES


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _system(course: Course, context: dict[str, Any], mode: str = "qa") -> str:
    from .prompts import build_system

    return build_system(
        course,
        mode,
        **{
            k: context[k]
            for k in ("deck", "slide", "selection", "region")
            if k in context
        },
    )


def _region_image(course: Course, context: dict[str, Any]) -> Path | None:
    region, deck, slide = (
        context.get("region"),
        context.get("deck"),
        context.get("slide"),
    )
    if not region or not deck or not slide:
        return None
    source = course.deck_dir(deck) / "slides" / f"{int(slide):03d}.webp"
    if not source.is_file():
        return None
    try:
        with Image.open(source) as image:
            w, h = image.size
            x0 = max(0, min(w, round(float(region["x"]) * w)))
            y0 = max(0, min(h, round(float(region["y"]) * h)))
            x1 = max(
                x0 + 1, min(w, round((float(region["x"]) + float(region["w"])) * w))
            )
            y1 = max(
                y0 + 1, min(h, round((float(region["y"]) + float(region["h"])) * h))
            )
            fd, name = tempfile.mkstemp(prefix="marginalia-region-", suffix=".png")
            os.close(fd)
            output = Path(name)
            image.crop((x0, y0, x1, y1)).save(output)
            return output
    except (KeyError, TypeError, ValueError, OSError):
        return None


def _history_prompt(messages: list[dict[str, Any]], message: str) -> str:
    history = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages[-12:]
    )
    return f"先前對話：\n{history}\n\n使用者：{message}" if history else message


_locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


async def stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    course = Course(request["course"])
    chat_id = request.get("chatId") or uuid.uuid4().hex
    if not isinstance(chat_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", chat_id):
        raise ValueError("對話 ID 格式不正確")
    key = (str(course.dir.resolve()), chat_id)
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        events = _stream({**request, "chatId": chat_id})
        try:
            async for event in events:
                yield event
        finally:
            await events.aclose()


async def _stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    course = Course(request["course"])
    check_course(course)
    chat_id = request["chatId"]
    path = course.chats_dir / f"{chat_id}.json"
    saved = read_json(
        path,
        {
            "id": chat_id,
            "title": request["message"][:50],
            "mode": request.get("mode", "qa"),
            "messages": [],
        },
    )
    mode = saved.get("mode", "qa")
    if mode not in MODES:
        raise ValueError("聊天模式不正確")
    messages = saved.get("messages", [])
    context = request.get("context") or {}
    prompt = _history_prompt(messages, request["message"])
    saved["messages"] = [
        *messages,
        {"role": "user", "content": request["message"], "createdAt": _now()},
    ]
    yield {"type": "start", "chatId": chat_id}
    response = ""
    done = None
    image = _region_image(course, context)
    events = None
    try:
        system = await asyncio.to_thread(_system, course, context, mode)
        if request.get("account", "claude") == "claude":
            call = claude.Call(
                prompt=prompt,
                system=system,
                images=[image] if image else [],
                model=request.get("model", "sonnet"),
                effort=request.get("effort"),
                cwd=course.dir,
                tools=["Read", "Grep", "Glob"],
                max_turns=8,
                read_root=course.dir,
            )
            events = claude.stream(call)
        else:
            events = codex_chat.stream(
                system + "\n\n" + prompt,
                request["account"],
                request.get("model", "gpt-5"),
                request.get("effort", "medium"),
                image,
            )
        async for event in events:
            if event["type"] == "text":
                response += event["delta"]
            if event["type"] == "done":
                done = {**event, "chatId": chat_id}
            else:
                yield event
        saved["messages"].append(
            {"role": "assistant", "content": response, "createdAt": _now()}
        )
        saved["updatedAt"] = _now()
        check_course(course)
        write_json(path, saved)
        yield done or {"type": "done", "chatId": chat_id}
    finally:
        if events:
            await events.aclose()
        if image:
            image.unlink(missing_ok=True)
