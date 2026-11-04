"""Plan across decks, draft and review bounded sections, resuming completed steps."""

from __future__ import annotations

import re

from .. import config
from .context import ExamContext, Progress, Section
from .generation import GenerationError, checkpoint, data, parallel
from .past import parse_uploads
from .prompts import (
    COMPACT_SYSTEM,
    HANDOUT_REVIEW,
    HANDOUT_SYSTEM,
    MAP_SYSTEM,
    PLAN_TASK,
)
from .schema import json_reply
from .study import material, sources, topics

_SOURCES = re.compile(r"\A<!--\s*sources:\s*(.*?)\s*-->\s*\n?", re.IGNORECASE)
_REF = re.compile(r"([\w][\w-]*)#(\d+)")
TOTAL_CHARS = 30_000


def split_sections(text: str) -> list[Section]:
    """`# title` + optional `<!-- sources: deck#n, … -->` + body, repeated."""
    text = re.sub(r"\A```(?:markdown|md)?\s*\n(.*)\n```\s*\Z", r"\1", text.strip(), flags=re.DOTALL)
    out = []
    for chunk in re.split(r"^#\s+", text, flags=re.MULTILINE)[1:]:
        title, _, body = chunk.partition("\n")
        body = body.strip()
        refs = []
        if m := _SOURCES.match(body):
            refs = [(d, int(i)) for d, i in _REF.findall(m[1])]
            body = body[m.end():].strip()
        if title.strip() and body:
            out.append(Section(title=title.strip()[:120], markdown=body, sources=refs))
    return out


def parse_plan(reply: str, mapped: list[dict]) -> list[dict]:
    plan = json_reply(reply, list)
    if not 1 <= len(plan) <= 12:
        raise ValueError("講義須規劃 1–12 節")
    assigned = []
    titles = set()
    for item in plan:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
            raise ValueError("每節都需要標題")
        if item["title"] in titles:
            raise ValueError("章節標題不可重複")
        titles.add(item["title"])
        if not isinstance(item.get("topics"), list) or not item["topics"] or any(not isinstance(t, str) for t in item["topics"]):
            raise ValueError("每節都要分配核心主題 id")
        assigned.extend(item["topics"])
    if len(assigned) != len(set(assigned)) or set(assigned) != {t["id"] for t in mapped}:
        raise ValueError("大綱必須涵蓋每個主題一次且僅一次，不可遺漏或重複")
    return [{"title": item["title"].strip(), "topics": item["topics"]} for item in plan]


def section_body(reply: str, limit: int) -> str:
    """Unwrap presentation-only headings/fences before checking the section's actual body."""
    body = re.sub(r"\A```(?:markdown|md)\s*\n(.*)\n```\s*\Z", r"\1", reply.strip(), flags=re.DOTALL).strip()
    body = re.sub(r"\A#{1,2}\s+[^\n]+\n+\s*(?=> \[!IMPORTANT\])", "", body)
    if not body or len(body) > limit:
        raise ValueError(f"本節須有內容且不超過 {limit} 字元，目前 {len(body)} 字元；英文字母、空白、標點、markdown 都計入，請再精簡")
    if not body.startswith("> [!IMPORTANT]") or "==" not in body:
        raise ValueError("本節須以 IMPORTANT 提示框開始並標示核心結論")
    if re.search(r"^#\s", body, re.MULTILINE) or body.startswith("```"):
        raise ValueError("僅輸出 markdown 本文，子標題使用 ##")
    return body


async def write_handout(ctx: ExamContext, progress: Progress) -> list[Section]:
    mapped = await topics(ctx, lambda f, m: progress(f * 0.25, m))
    if not mapped:
        raise GenerationError("考試範圍沒有可整理的投影片")
    parsed = await parse_uploads(ctx, lambda f, m: progress(0.25 + f * 0.03, m))
    papers = [{"upload": p.upload, "number": p.number, "type": p.type, "prompt": p.prompt[:400]} for p in parsed[:200]]
    prompt = f"{PLAN_TASK}\n\n主題 JSON：{data(mapped)}\n考古題 JSON：{data(papers)}"
    plan = await checkpoint(ctx, "outline", prompt, MAP_SYSTEM, lambda s: parse_plan(s, mapped))
    progress(0.3, f"大綱完成：{len(plan)} 節，涵蓋 {len(ctx.decks)} 份簡報")
    by_id, by_ref = {t["id"]: t for t in mapped}, sources(ctx)
    done = 0
    # Include review and exercises in this conservative reading budget (about 180 chars/minute).
    target = min(6_000, (TOTAL_CHARS * 9 // 10) // len(plan))
    limit = 6_000  # Intermediate drafts may grow during review; compact the complete handout afterward.

    async def one(chapter):
        nonlocal done
        selected = [by_id[t] for t in chapter["topics"]]
        refs = list(dict.fromkeys(r for t in selected for r in t["sources"]))
        evidence = material(ctx, refs)
        figures = [by_ref[r].image for r in refs if by_ref[r].image][:2]
        base = (f"整份大綱 JSON：{data(plan)}\n本節 JSON：{data(chapter)}\n核心主題 JSON：{data(selected)}\n"
                f"來源素材 JSON：{data(evidence)}\n考古題 JSON：{data(papers)}\n"
                f"本節以 {target * 3 // 4} 字元為目標，暫時上限 {limit} 字元（含 markdown）。只輸出本節本文。")

        parse = lambda reply: section_body(reply, limit)

        draft = await checkpoint(ctx, "section", base, HANDOUT_SYSTEM, parse, figures, attempts=4)
        body = await checkpoint(ctx, "section-review", f"{base}\n草稿 JSON：{data(draft)}\n{HANDOUT_REVIEW}",
                                HANDOUT_SYSTEM, parse, figures, attempts=4)
        done += 1
        progress(0.3 + 0.6 * done / len(plan), f"講義撰寫與核對 {done}/{len(plan)}（{chapter['title']}）")
        return Section(chapter["title"], body, [(by_ref[r].deck, by_ref[r].index) for r in refs])

    sections = await parallel(plan, one, config.GEN_CONCURRENCY)
    return await compact_sections(ctx, sections, lambda f, m: progress(0.9 + 0.1 * f, m))


async def compact_sections(ctx: ExamContext, sections: list[Section], progress: Progress) -> list[Section]:
    """Budget the complete handout, allowing longer chapters to borrow from shorter ones."""
    current = sections
    for round_index in range(3):
        total = sum(len(s.markdown) for s in current)
        if total <= TOTAL_CHARS:
            progress(1.0, f"講義完成：{len(current)} 節，{total} 字元")
            return current
        current = await _compact_round(ctx, current, total, round_index, progress)
    if sum(len(s.markdown) for s in current) > TOTAL_CHARS:
        raise GenerationError("精簡後講義仍超過三小時閱讀預算，請縮小範圍後重新產生")
    progress(1.0, f"講義完成：{len(current)} 節")
    return current


async def _compact_round(ctx: ExamContext, sections: list[Section], total: int, round_index: int,
                         progress: Progress) -> list[Section]:
    done = 0

    async def one(section):
        nonlocal done
        # Per-chapter shares guide the editor; only the complete handout has a hard reading budget.
        budget = TOTAL_CHARS * (10 - 2 * round_index) // 10
        target = max(1, len(section.markdown) * budget // total)
        prompt = (f"整份講義超過三小時預算，精簡這一節。最多 {target} 字元（含所有 markdown），"
                  f"以 {target // 2} 字元為目標，留餘裕。只刪重複與贅字、合併句子；保留核心機制、"
                  "公式、必要圖表與易錯提醒，只留一個必要例子。刪除節末自我測驗及 details 答案，完整練習已另附模擬考。"
                  "不改數字、不新增原稿沒有的事實或來源。"
                  f"只輸出完整 markdown 本文。\n節標題 JSON：{data(section.title)}\n原稿 JSON：{data(section.markdown)}")
        body = await checkpoint(ctx, "section-compact", prompt, COMPACT_SYSTEM,
                                lambda reply: section_body(reply, 6_000), attempts=4)
        done += 1
        progress((round_index + done / len(sections)) / 3, f"全份講義精簡 {round_index + 1}：{done}/{len(sections)}")
        return Section(section.title, body, section.sources)

    return await parallel(sections, one, config.GEN_CONCURRENCY)
