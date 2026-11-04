"""Transcribe and independently verify every paper, including tables in image uploads."""

from __future__ import annotations

import re
from dataclasses import asdict
from itertools import pairwise

from .. import config
from .context import ExamContext, PastQuestion, Progress
from .generation import GenerationError, checkpoint, data, parallel
from .prompts import PAST_REVIEW, PAST_SYSTEM, PAST_TASK
from .schema import TYPES, json_reply

MAX_PER_UPLOAD = 100
TEXT_CHARS = 36_000
_ZH = "一二三四五六七八九十百"
_QUESTION = re.compile(
    r"^[ \t]{0,3}(?:#{1,6}[ \t]+)?(?:"
    r"(?:Question|Q)[ \t]*(?P<named_num>[0-9]{1,3})\b|"
    rf"第(?P<named_zh>[0-9{_ZH}]+)題|"
    r"(?P<arabic>[0-9]{1,3})[.．、:：)）](?![0-9])|"
    rf"(?P<chinese>[{_ZH}]+)[.．、:：)）]|"
    r"[（(](?P<paren_num>[0-9]{1,3})[)）]|"
    rf"[（(](?P<paren_zh>[{_ZH}]+)[)）])",
    re.MULTILINE | re.IGNORECASE,
)


def text_parts(text: str) -> list[str]:
    """Pack complete numbered questions, repeating the shared preamble in each batch.

    An ambiguous large paper fails visibly instead of silently cutting a stem/table in half. Small unnumbered
    papers still travel whole; numbering is only needed to split material exceeding a single-call budget.
    """
    if len(text) <= TEXT_CHARS:
        return [text]
    matches = list(_QUESTION.finditer(text))
    if not matches:
        raise GenerationError("文字考古題太長且沒有可辨識的題號，請依題目分檔或加入題號後重試")
    # The first numbering family is the parent level. Other families (一、 → 1. → (1)) stay inside it.
    family = matches[0].lastgroup
    parents = [m for m in matches if m.lastgroup == family]
    labels = [m[family] for m in parents]
    if len(labels) != len(set(labels)) or (all(n.isdecimal() for n in labels)
                                         and [int(n) for n in labels] != sorted(int(n) for n in labels)):
        raise GenerationError("長考卷題號階層不明，請依含共同題幹的完整大題分檔後重試")
    starts = [m.start() for m in parents]
    preamble = text[:starts[0]]
    out, current = [], preamble
    for a, b in pairwise([*starts, len(text)]):
        block = text[a:b]
        if len(preamble) + len(block) > TEXT_CHARS:
            raise GenerationError("單一考古題或共同題幹過長，請依完整子題分檔後重試")
        if len(current) + len(block) > TEXT_CHARS:
            out.append(current)
            current = preamble
        current += block
    if current != preamble:
        out.append(current)
    return out


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
                # Keep repeated subquestions inside a batch; only repeated shared context crosses batches.
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
