"""Scope + past papers → quiz questions. Minimal version: one model call (owned by the generation card)."""

from __future__ import annotations

from .context import ExamContext, PastQuestion, Progress
from .prompts import QUIZ_SYSTEM, QUIZ_TASK, deck_text, past_text
from .schema import TYPES, json_reply

BUDGET = 100_000
TYPE_NAMES = {"choice": "選擇", "fill": "填空", "short": "簡答", "essay": "問答", "calc": "計算"}


async def write_quiz(ctx: ExamContext, past: list[PastQuestion], progress: Progress) -> list[dict]:
    options = ctx.exam.get("options") or {}
    count = max(len(past) + 5, int(options.get("questionCount") or 15))
    types = [t for t in options.get("types") or TYPES if t in TYPES] or list(TYPES)
    per_deck = BUDGET // max(1, len(ctx.decks))
    material = "\n\n".join(deck_text(d, per_deck) for d in ctx.decks)
    task = QUIZ_TASK.format(count=count, types="、".join(TYPE_NAMES[t] for t in types))
    progress(0.1, "出題中")
    reply = await ctx.llm(f"{material}\n\n## 考古題\n{past_text(past)}\n\n{task}", system=QUIZ_SYSTEM)
    questions = [q for q in json_reply(reply, list) if isinstance(q, dict)]
    progress(1.0, f"產生 {len(questions)} 題")
    return questions
