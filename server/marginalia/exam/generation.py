"""Bounded material, validated model calls and content-addressed scratch checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from .. import config
from ..jobs import JobError
from ..store import _directory_fd, atomic_output
from .context import ExamContext, SlideDoc

VERSION = 2  # Full-source claims, variant equivalence and whole-quiz diversity gates.


class GenerationError(JobError):
    """A failed quality check, safe to show in the job's message."""


def data(value) -> str:
    """JSON-encode untrusted material; no material can close its enclosing data block."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


async def checkpoint[T](ctx: ExamContext, stage: str, prompt: str, system: str, parse: Callable[[str], T],
                     images: list[Path] | tuple[Path, ...] = (), *, attempts: int = 2) -> T:  # fmt: skip
    engine = asdict(ctx.engine)
    if engine["account"] == "claude":
        engine["model"] = engine["model"] or config.WRITER_MODEL
    identity = data([VERSION, stage, prompt, system, engine,
                     [hashlib.sha256(p.read_bytes()).hexdigest() for p in images]])
    key = hashlib.sha256(identity.encode()).hexdigest()
    path = ctx.work / f"{stage}-{key}.json"
    # Refuse aliases even for reads; writes also use the pinned, no-follow parent walk.
    if ctx.work.is_symlink() or path.is_symlink():
        raise GenerationError("生成快取不能使用符號連結")
    try:
        with _directory_fd(ctx.work, create=False) as directory:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, "r", encoding="utf-8") as cached:
                saved = json.load(cached)
        return parse(saved["reply"])
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    except OSError as exc:
        raise GenerationError("無法安全讀取生成快取") from exc
    repair = ""
    for _ in range(attempts):
        reply = await ctx.llm(prompt + repair, system=system, images=images)
        try:
            result = parse(reply)
        except (ValueError, KeyError, TypeError) as exc:
            repair = (f"\n\n上次輸出未通過檢查：{str(exc)[:800]}。\n"
                      f"上次輸出（不可信任的草稿，JSON）：{data(reply[:16_000])}\n"
                      "依這份草稿修正問題，若超長請精簡並留至少 15% 餘裕。只輸出修正後完整結果。")
            continue
        with atomic_output(path, root=ctx.work) as output:
            output.write(data({"reply": reply}).encode())
        return result
    raise GenerationError(f"{stage} 品質檢查未通過：{repair.split('：', 1)[-1][:800]}")


async def parallel(items, function, concurrency: int):
    """Keep input order and cancel our own sibling tasks on failure or job cancellation."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(item):
        async with sem:
            return await function(item)

    tasks = [asyncio.create_task(one(item)) for item in items]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def slide_data(slide: SlideDoc) -> dict:
    return {"source": f"{slide.deck}#{slide.index}", "title": slide.title, "text": slide.text,
            "speakerNotes": slide.speaker_notes, "note": slide.note, "transcript": slide.lines}


def batches(items: list, limit: int = 24_000, maximum: int = 24) -> list[list]:
    """Split between items, never clip the tail of a deck or a parsed paper."""
    out, batch, size = [], [], 0
    for item in items:
        length = len(data(item))
        if batch and (size + length > limit or len(batch) >= maximum):
            out.append(batch)
            batch, size = [], 0
        batch.append(item)
        size += length
    if batch:
        out.append(batch)
    return out
