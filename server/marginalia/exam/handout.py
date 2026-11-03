"""Scope → handout sections. Minimal version: one model call per deck (owned by the generation card)."""

from __future__ import annotations

import asyncio
import re

from .. import config
from .context import ExamContext, Progress, Section
from .prompts import HANDOUT_SYSTEM, HANDOUT_TASK, deck_text

DECK_BUDGET = 60_000
_SOURCES = re.compile(r"\A<!--\s*sources:\s*(.*?)\s*-->\s*\n?", re.IGNORECASE)
_REF = re.compile(r"([\w][\w-]*)#(\d+)")


def split_sections(text: str) -> list[Section]:
    """`# title` + optional `<!-- sources: deck#n, … -->` + body, repeated."""
    text = re.sub(r"\A```(?:markdown|md)?\s*\n(.*)\n```\s*\Z", r"\1", text.strip(), flags=re.DOTALL)
    out = []
    for chunk in re.split(r"^#\s+", text, flags=re.MULTILINE)[1:]:
        title, _, body = chunk.partition("\n")
        body = body.strip()
        sources: list[tuple[str, int]] = []
        if m := _SOURCES.match(body):
            sources = [(d, int(i)) for d, i in _REF.findall(m[1])]
            body = body[m.end() :].strip()
        if title.strip() and body:
            out.append(Section(title=title.strip()[:120], markdown=body, sources=sources))
    return out


async def write_handout(ctx: ExamContext, progress: Progress) -> list[Section]:
    done = 0
    sem = asyncio.Semaphore(max(1, config.GEN_CONCURRENCY))

    async def one(deck) -> list[Section]:
        nonlocal done
        async with sem:
            reply = await ctx.llm(f"{deck_text(deck, DECK_BUDGET)}\n\n{HANDOUT_TASK}", system=HANDOUT_SYSTEM)
        done += 1
        progress(done / len(ctx.decks), f"撰寫講義 {done}/{len(ctx.decks)}（{deck.title}）")
        return split_sections(reply)

    results = await asyncio.gather(*(one(d) for d in ctx.decks))
    return [s for sections in results for s in sections]
