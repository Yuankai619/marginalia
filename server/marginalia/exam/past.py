"""Past papers → PastQuestion list. Minimal version: one model call per upload (owned by the generation card)."""

from __future__ import annotations

from ..notes.material import clip
from .context import ExamContext, PastQuestion, Progress
from .prompts import PAST_SYSTEM, PAST_TASK
from .schema import TYPES, json_reply


async def parse_uploads(ctx: ExamContext, progress: Progress) -> list[PastQuestion]:
    out: list[PastQuestion] = []
    for n, upload in enumerate(ctx.uploads, 1):
        progress((n - 1) / len(ctx.uploads), f"讀取考古題 {n}/{len(ctx.uploads)}")
        material = f"## 考古題檔案：{upload.name}\n" + (
            clip(upload.text, 60_000) if upload.kind == "text" else "（見附圖）"
        )
        reply = await ctx.llm(f"{material}\n\n{PAST_TASK}", system=PAST_SYSTEM,
                              images=[upload.path] if upload.kind == "image" else [])  # fmt: skip
        for item in json_reply(reply, list):
            if not isinstance(item, dict) or not isinstance(item.get("prompt"), str) or not item["prompt"].strip():
                continue
            options = [o for o in item.get("options") or [] if isinstance(o, dict)]
            out.append(PastQuestion(
                upload=upload.name, number=str(item.get("number") or ""),
                type=item.get("type") if item.get("type") in TYPES else "short", prompt=item["prompt"].strip(),
                options=options, answer_hint=str(item.get("answer_hint") or ""),
            ))  # fmt: skip
    progress(1.0, f"考古題共 {len(out)} 題")
    return out
