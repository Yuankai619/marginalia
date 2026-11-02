"""Read-only course chat backed by the locally logged-in Claude or Codex CLI."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from ..llm import claude
from ..store import Course, read_json, write_json


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _note(course: Course, deck: str | None, slide: int | None) -> str:
    if not deck or not slide:
        return ""
    try:
        return course.note_path(deck, slide).read_text("utf-8")
    except FileNotFoundError:
        return ""


def _system(course: Course, context: dict[str, Any]) -> str:
    try:
        from .prompts import build_system

        return build_system(course, context)
    except ImportError:
        deck, slide = context.get("deck"), context.get("slide")
        titles = [
            f"{d['title']}："
            + "、".join(s.get("title", "") for s in course.slides(d["id"])[:30])
            for d in course.manifest()["decks"]
        ]
        current = (
            next((s for s in course.slides(deck) if s.get("index") == slide), {})
            if deck
            else {}
        )
        selection = (context.get("selection") or {}).get("text", "")
        return "\n".join(
            [
                "你是課程助教。使用繁體中文、依資料作答；不確定就明說。",
                "課程投影片：" + "\n".join(titles),
                "目前投影片：" + current.get("text", ""),
                "目前筆記：" + _note(course, deck, slide),
                "選取文字：" + selection,
            ]
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


async def _codex(
    prompt: str, course: Course, account: str, model: str, effort: str
) -> AsyncIterator[dict[str, Any]]:
    home = Path.home() / (".codex" if account == "codex" else f".{account}")
    env = {**os.environ, "CODEX_HOME": str(home)}
    process = await asyncio.create_subprocess_exec(
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "-C",
        str(course.dir),
        "-m",
        model,
        "-c",
        f"model_reasoning_effort={effort}",
        prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdout is not None
    async for raw in process.stdout:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type", "")
        if kind in {"item.completed", "response.output_text.delta"}:
            item = event.get("item", {})
            text = event.get("delta") or item.get("text") or item.get("content")
            if isinstance(text, str):
                yield {"type": "text", "delta": text}
    code = await process.wait()
    if code:
        raise RuntimeError("Codex 執行失敗")
    yield {"type": "done"}


async def stream(request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    course = Course(request["course"])
    chat_id = request.get("chatId") or uuid.uuid4().hex
    if not isinstance(chat_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", chat_id):
        raise ValueError("對話 ID 格式不正確")
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
    messages = saved.get("messages", [])
    context = request.get("context") or {}
    prompt = _history_prompt(messages, request["message"])
    saved["messages"] = [
        *messages,
        {"role": "user", "content": request["message"], "createdAt": _now()},
    ]
    yield {"type": "start", "chatId": chat_id}
    response = ""
    image = _region_image(course, context)
    try:
        if request.get("account", "claude") == "claude":
            call = claude.Call(
                prompt=prompt,
                system=_system(course, context),
                images=[image] if image else [],
                model=request.get("model", "sonnet"),
                effort=request.get("effort"),
                cwd=course.dir,
                tools=["Read", "Grep", "Glob"],
                max_turns=8,
            )
            events = claude.stream(call)
        else:
            events = _codex(
                _system(course, context) + "\n\n" + prompt,
                course,
                request["account"],
                request.get("model", "gpt-5"),
                request.get("effort", "medium"),
            )
        async for event in events:
            if event["type"] == "text":
                response += event["delta"]
            if event["type"] == "done":
                event = {**event, "chatId": chat_id}
            yield event
        saved["messages"].append(
            {"role": "assistant", "content": response, "createdAt": _now()}
        )
        saved["updatedAt"] = _now()
        write_json(path, saved)
    finally:
        if image:
            image.unlink(missing_ok=True)
