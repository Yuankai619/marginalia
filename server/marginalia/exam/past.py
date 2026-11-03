"""Past papers → PastQuestion list. Minimal version: one model call per upload (owned by the generation card)."""

from __future__ import annotations

import asyncio

from .. import config
from ..notes.material import clip
from .context import ExamContext, PastQuestion, Progress
from .prompts import PAST_SYSTEM, PAST_TASK
from .schema import TYPES, json_reply

MAX_PER_UPLOAD = 100


async def parse_uploads(ctx: ExamContext, progress: Progress) -> list[PastQuestion]:
    sem = asyncio.Semaphore(max(1, config.GEN_CONCURRENCY))
    done = 0

    async def one(upload) -> list[PastQuestion]:
        nonlocal done
        material = f"## 考古題檔案：{upload.name}\n" + (
            clip(upload.text, 60_000) if upload.kind == "text" else "（見附圖）"
        )
        async with sem:
            reply = await ctx.llm(f"{material}\n\n{PAST_TASK}", system=PAST_SYSTEM,
                                  images=[upload.path] if upload.kind == "image" else [])  # fmt: skip
        done += 1
        progress(done / len(ctx.uploads), f"讀取考古題 {done}/{len(ctx.uploads)}")
        out = []
        for item in json_reply(reply, list)[:MAX_PER_UPLOAD]:
            if not isinstance(item, dict) or not isinstance(item.get("prompt"), str) or not item["prompt"].strip():
                continue
            options = [o for o in item.get("options") or [] if isinstance(o, dict)]
            out.append(PastQuestion(
                upload=upload.name, number=str(item.get("number") or ""),
                type=item.get("type") if item.get("type") in TYPES else "short", prompt=item["prompt"].strip(),
                options=options, answer_hint=str(item.get("answer_hint") or ""),
            ))  # fmt: skip
        return out

    # Upload order is kept: past-paper questions appear in the quiz in the order they were uploaded.
    results = await asyncio.gather(*(one(u) for u in ctx.uploads))
    return [q for questions in results for q in questions]
