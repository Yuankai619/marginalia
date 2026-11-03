"""Plan across decks, draft and review bounded sections, resuming completed steps."""

from __future__ import annotations

import re

from .. import config
from .context import ExamContext, Progress, Section
from .generation import GenerationError, checkpoint, data, parallel
from .past import parse_uploads
from .prompts import HANDOUT_REVIEW, HANDOUT_SYSTEM, MAP_SYSTEM, PLAN_TASK
from .schema import json_reply
from .study import material, sources, topics

_SOURCES = re.compile(r"\A<!--\s*sources:\s*(.*?)\s*-->\s*\n?", re.IGNORECASE)
_REF = re.compile(r"([\w][\w-]*)#(\d+)")
TOTAL_CHARS = 27_000


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
    # Include review and exercises in this conservative reading budget (about 150 chars/minute).
    limit = min(6_000, TOTAL_CHARS // len(plan))

    async def one(chapter):
        nonlocal done
        selected = [by_id[t] for t in chapter["topics"]]
        refs = list(dict.fromkeys(r for t in selected for r in t["sources"]))
        evidence = material(ctx, refs)
        figures = [by_ref[r].image for r in refs if by_ref[r].image][:2]
        base = (f"整份大綱 JSON：{data(plan)}\n本節 JSON：{data(chapter)}\n核心主題 JSON：{data(selected)}\n"
                f"來源素材 JSON：{data(evidence)}\n考古題 JSON：{data(papers)}\n"
                f"本節最多 {limit} 字元（含 markdown），以 60–80% 為目標。只輸出本節本文。")

        def parse(reply):
            body = reply.strip()
            if not body or len(body) > limit:
                raise ValueError(f"本節須有內容且不超過 {limit} 字元，目前 {len(body)} 字元；英文字母、空白、標點、markdown 都計入，請再精簡")
            if not body.startswith("> [!IMPORTANT]") or "==" not in body:
                raise ValueError("本節須以 IMPORTANT 提示框開始並標示核心結論")
            if re.search(r"^#\s", body, re.MULTILINE) or body.startswith("```"):
                raise ValueError("僅輸出 markdown 本文，子標題使用 ##")
            return body

        draft = await checkpoint(ctx, "section", base, HANDOUT_SYSTEM, parse, figures)
        body = await checkpoint(ctx, "section-review", f"{base}\n草稿 JSON：{data(draft)}\n{HANDOUT_REVIEW}",
                                HANDOUT_SYSTEM, parse, figures)
        done += 1
        progress(0.3 + 0.7 * done / len(plan), f"講義撰寫與核對 {done}/{len(plan)}（{chapter['title']}）")
        return Section(chapter["title"], body, [(by_ref[r].deck, by_ref[r].index) for r in refs])

    return await parallel(plan, one, config.GEN_CONCURRENCY)
