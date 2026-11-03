"""Generate past papers first, then balanced new slots, checking each batch's answers."""

from __future__ import annotations

import re
from dataclasses import asdict

from .. import config
from .context import ExamContext, PastQuestion, Progress
from .generation import GenerationError, batches, checkpoint, data, parallel
from .prompts import QUIZ_PAST, QUIZ_REVIEW, QUIZ_SYSTEM
from .schema import OPTION_IDS, TYPES, clean_question, json_reply
from .study import material, topics

MAX_QUESTIONS = 200


def validate(reply: str, ctx: ExamContext, expected: list[dict], *, past: bool) -> list[dict]:
    raw = json_reply(reply, list)
    if len(raw) != len(expected):
        raise ValueError(f"本批必須剛好 {len(expected)} 題，順序相同")
    out = []
    for item, slot in zip(raw, expected, strict=True):
        question = clean_question(item, ctx.slide_count())
        if question is None or not question.get("solution") or not question.get("sources"):
            raise ValueError("每題須有有效題型、答案、完整詳解與範圍內投影片來源")
        if past:
            if question["origin"] != "past" or question.get("pastRef") != slot["upload"]:
                raise ValueError("考古題 origin/pastRef 必須與來源相符")
            if not question["prompt"].startswith(slot["prompt"]):
                raise ValueError("考古題題幹必須完整保留原文並放在 prompt 開頭")
            printed_options = [{"id": OPTION_IDS[i], "text": o["text"].strip()}
                               for i, o in enumerate(slot["options"][:8])]
            if (slot["type"] == "choice" and "[無法辨識]" not in slot["prompt"]
                    and (question["type"] != "choice" or question["options"] != printed_options)):
                raise ValueError("考古選擇題必須保留題型與完整選項")
        elif question["type"] != slot["type"] or question["origin"] != "new":
            raise ValueError("新題須依指定題型與順序出題，origin 為 new")
        if question["type"] == "choice" and bool(item.get("multiple")) != (len(question["answer"]) > 1):
            raise ValueError("單選需一個答案，多選需多個答案，multiple 必須一致")
        if question["type"] in {"short", "essay", "calc"}:
            rubric = question.get("rubric") or []
            if not rubric or sum(r["points"] for r in rubric) != item.get("points"):
                raise ValueError("主觀題須有 rubric，配分加總等於 points")
        if not past and not any(f"{s['deck']}#{s['slide']}" in slot["topic"]["sources"] for s in question["sources"]):
            raise ValueError("新題來源必須包含指定核心主題的投影片")
        out.append(question)
    return out


def new_slots(ctx: ExamContext, mapped: list[dict], past_count: int) -> list[dict]:
    options = ctx.exam.get("options") or {}
    types = [t for t in TYPES if t in (options.get("types") or TYPES)]
    types = types or list(TYPES)
    count = min(MAX_QUESTIONS - past_count, max(5, len(types), len(ctx.decks),
                                               int(options.get("questionCount") or 20) - past_count))
    # Rotate across decks before revisiting one: later decks cannot disappear when the requested quiz is short.
    ordered = []
    groups = [[t for t in mapped if any(r.startswith(f"{d.id}#") for r in t["sources"])] for d in ctx.decks]
    for i in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if i < len(group) and group[i] not in ordered:
                ordered.append(group[i])
    if not ordered:
        raise GenerationError("沒有可用來出題的核心主題")
    levels = ["基礎", "理解", "理解", "應用", "基礎", "理解", "理解", "應用", "基礎", "理解"]
    return [{"number": i + 1, "type": types[i % len(types)], "topic": ordered[i % len(ordered)], "difficulty": levels[i % len(levels)],
             "angle": ["定義與因果", "比較與取捨", "情境應用", "找出錯誤"][i // max(1, len(ordered)) % 4]}
            for i in range(max(0, count))]


def relevant(mapped: list[dict], batch: list[dict]) -> list[dict]:
    """Add direct source evidence to the global topic map for past-paper answer checking."""
    text = " ".join(p["prompt"] for p in batch).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9_-]{2,}|[\u4e00-\u9fff]{2}", text))
    ranked = sorted(mapped, key=lambda t: sum(token in (t["title"] + t["explanation"]).lower() for token in tokens), reverse=True)
    return ranked[:4]


async def write_quiz(ctx: ExamContext, past: list[PastQuestion], progress: Progress) -> list[dict]:
    mapped = await topics(ctx, lambda f, m: progress(f * 0.2, m))
    preserved = [asdict(p) for p in past[:MAX_QUESTIONS]]
    jobs = [(True, batch) for batch in batches(preserved, limit=16_000, maximum=4)]
    slots = new_slots(ctx, mapped, len(preserved))
    jobs.extend((False, batch) for batch in batches(slots, limit=16_000, maximum=5))
    done = 0

    async def one(job):
        nonlocal done
        is_past, batch = job
        selected = relevant(mapped, batch) if is_past else [s["topic"] for s in batch]
        refs = list(dict.fromkeys(r for t in selected for r in t["sources"]))
        difficulty = [{"type": p["type"], "topic": p["prompt"][:240]} for p in preserved]
        base = (f"核心主題 JSON：{data(mapped if is_past else selected)}\n"
                f"來源素材 JSON：{data(material(ctx, refs))}\n"
                f"考古題難度參考 JSON：{data(difficulty)}\n")
        if is_past:
            task = f"{QUIZ_PAST}\n本批考古題 JSON：{data(batch)}"
        else:
            task = (f"依下列題型、主題與順序出剛好 {len(batch)} 題新題，避免重複考同一件事。\n"
                    f"本批出題配置 JSON：{data(batch)}")
        parse = lambda reply: validate(reply, ctx, batch, past=is_past)
        draft = await checkpoint(ctx, "quiz-past" if is_past else "quiz-new", base + task, QUIZ_SYSTEM, parse)
        result = await checkpoint(ctx, "quiz-review", f"{base}{task}\n草稿 JSON：{data(draft)}\n{QUIZ_REVIEW}",
                                  QUIZ_SYSTEM, parse)
        done += 1
        progress(0.2 + 0.8 * done / len(jobs), f"題目與答案核對 {done}/{len(jobs)} 批")
        return result

    results = await parallel(jobs, one, config.GEN_CONCURRENCY)
    questions = [q for batch in results for q in batch]
    seen = set()
    for q in questions:
        if q["origin"] == "new":
            key = re.sub(r"\W+", "", q["prompt"]).casefold()
            if key in seen:
                raise GenerationError("新題出現重複題幹，請調整題目數或範圍後重新產生")
            seen.add(key)
    progress(1.0, f"完成 {len(questions)} 題（考古題 {len(preserved)} 題）")
    return questions
