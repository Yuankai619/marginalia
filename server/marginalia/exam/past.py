"""Transcribe and independently verify every paper, including tables in image uploads."""

from __future__ import annotations

from dataclasses import asdict

from .. import config
from .context import ExamContext, PastQuestion, Progress
from .generation import checkpoint, data, parallel
from .prompts import PAST_REVIEW, PAST_SYSTEM, PAST_TASK
from .schema import TYPES, json_reply

MAX_PER_UPLOAD = 100
TEXT_CHARS = 36_000
OVERLAP = 2_000


def text_parts(text: str) -> list[str]:
    """Overlapping windows keep question continuations; exact repeats are removed after verification."""
    if not text:
        return [""]
    return [text[start:start + TEXT_CHARS] for start in range(0, len(text), TEXT_CHARS - OVERLAP)]


def parse_questions(reply: str, upload: str) -> list[PastQuestion]:
    raw = json_reply(reply, list)
    if len(raw) > MAX_PER_UPLOAD:
        raise ValueError("每份考古題最多 100 題")
    out = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("prompt"), str) or not item["prompt"].strip():
            raise ValueError("每題都必須有完整題幹")
        if len(item["prompt"]) > 8_000:
            raise ValueError("單題題幹超過 8000 字，請依子題分開並保留共同題幹")
        options = item.get("options") or []
        if not isinstance(options, list) or any(not isinstance(o, dict) or not isinstance(o.get("text"), str) for o in options):
            raise ValueError("選項須為包含 id 與 text 的陣列")
        out.append(PastQuestion(
            upload=upload, number=str(item.get("number") or ""),
            type=item.get("type") if item.get("type") in TYPES else "short", prompt=item["prompt"].strip(),
            options=[{"id": str(o.get("id") or ""), "text": o["text"]} for o in options],
            answer_hint=str(item.get("answer_hint") or ""),
        ))
    return out


async def parse_uploads(ctx: ExamContext, progress: Progress) -> list[PastQuestion]:
    async with ctx._past_lock:
        if ctx._past is None:
            ctx._past = await _parse_uploads(ctx, progress)
        return ctx._past


async def _parse_uploads(ctx: ExamContext, progress: Progress) -> list[PastQuestion]:
    done = 0

    async def one(upload):
        nonlocal done
        out = []
        seen = set()
        images = [upload.path] if upload.kind == "image" else []
        for i, text in enumerate(text_parts(upload.text)):
            base = f"檔案 JSON：{data({'name': upload.name, 'part': i + 1, 'text': text})}\n{PAST_TASK}"
            parse = lambda reply: parse_questions(reply, upload.name)
            draft = await checkpoint(ctx, "past", base, PAST_SYSTEM, parse, images)

            def verified(reply, first=draft):
                result = parse_questions(reply, upload.name)
                if len(result) < len(first):
                    raise ValueError("核對後題數減少，請補回所有題目與子題")
                return result

            checked = await checkpoint(ctx, "past-review", f"{base}\n第一次轉錄 JSON：{data([asdict(p) for p in draft])}\n{PAST_REVIEW}",
                                       PAST_SYSTEM, verified, images)
            for question in checked:
                key = data([question.number, question.prompt, question.options])
                # Deduplicate only between overlapping windows, never repeated subquestions in the same window.
                if key not in seen:
                    out.append(question)
            seen.update(data([p.number, p.prompt, p.options]) for p in checked)
        done += 1
        progress(done / max(1, len(ctx.uploads)), f"考古題轉錄與核對 {done}/{len(ctx.uploads)}")
        return out[:MAX_PER_UPLOAD]

    results = await parallel(ctx.uploads, one, config.GEN_CONCURRENCY)
    if not ctx.uploads:
        progress(1.0, "沒有上傳考古題")
    return [q for questions in results for q in questions]
