"""Share a source-grounded topic map between the handout and quiz chains."""

from __future__ import annotations

import re

from .. import config
from .context import ExamContext, Progress
from .generation import GenerationError, batches, checkpoint, data, parallel, slide_data
from .prompts import MAP_SYSTEM, MAP_TASK, REDUCE_TASK
from .schema import json_reply


def sources(ctx: ExamContext) -> dict:
    return {f"{s.deck}#{s.index}": s for d in ctx.decks for s in d.slides}


def excerpt(text: str, budget: int) -> str:
    """Keep both ends and every trailing correction section, even when it exceeds the excerpt budget."""
    if len(text) <= budget:
        return text
    correction = re.search(r"(?im)^#{1,6}\s*(?:補充|勘誤|修正|更正|訂正|correction|errata)", text)
    tail = text[correction.start():] if correction else text[-max(1, budget // 2):]
    head = text[:max(0, budget - len(tail))]
    return head + "\n（中段節錄省略；核對時讀完整原頁）\n" + tail


def material(ctx: ExamContext, refs: list[str], budget: int = 48_000) -> list[dict]:
    """Writing excerpts retain corrections; semantic gates separately read full source batches."""
    by_ref = sources(ctx)
    selected = [by_ref[r] for r in dict.fromkeys(refs) if r in by_ref]
    share = budget // max(1, len(selected))
    out = []
    for slide in selected:
        item = slide_data(slide)
        for key in ("text", "speakerNotes", "note"):
            item[key] = excerpt(item[key], share // 4)
        item["transcript"] = excerpt(data(item["transcript"]), share // 4)
        out.append(item)
    return out


async def topics(ctx: ExamContext, progress: Progress) -> list[dict]:
    async with ctx._study_lock:
        if ctx._topics is not None:
            return ctx._topics
        chunks = [batch for deck in ctx.decks for batch in batches([slide_data(s) for s in deck.slides])]
        done = 0
        by_ref = sources(ctx)

        async def one(chunk):
            nonlocal done
            allowed = {s["source"] for s in chunk}

            def parse(reply):
                raw = json_reply(reply, list)
                if len(raw) > 6:
                    raise ValueError("每批最多 6 個核心主題；只有封面或行政事項可回空陣列")
                for item in raw:
                    if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
                        raise ValueError("主題缺少標題")
                    if not isinstance(item.get("explanation"), str) or not item["explanation"].strip():
                        raise ValueError("主題缺少解釋")
                    if len(item["title"]) > 120 or len(item["explanation"]) > 1500:
                        raise ValueError("主題標題最多 120 字、解釋最多 1500 字")
                    refs = item.get("sources")
                    if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in allowed for r in refs):
                        raise ValueError("主題必須引用本批實際投影片")
                return [{k: item[k] for k in ("title", "explanation", "sources")} for item in raw]

            # Image-only slides need vision even when no note/text was extracted.
            images = [by_ref[s["source"]].image for s in chunk
                      if not (s["text"].strip() or s["note"].strip()) and by_ref[s["source"]].image]
            result = await checkpoint(ctx, "topics", f"{MAP_TASK}\n\n素材 JSON：\n{data(chunk)}", MAP_SYSTEM, parse, images)
            done += 1
            progress(0.8 * done / max(1, len(chunks)), f"整理核心主題 {done}/{len(chunks)}")
            return result

        maps = await parallel(chunks, one, config.GEN_CONCURRENCY)
        merged = await consolidate(ctx, [t for m in maps for t in m],
                                   lambda f, m: progress(0.8 + 0.2 * f, m))
        ctx._topics = [{"id": f"t{i}", **topic} for i, topic in enumerate(merged, 1)]
        return ctx._topics


async def consolidate(ctx: ExamContext, mapped: list[dict], progress: Progress | None = None) -> list[dict]:
    """Reduce large maps per deck; each intermediate topic must be assigned exactly once."""
    progress = progress or (lambda *_: None)
    done = 0

    async def one_deck(deck):
        nonlocal done
        current = [t for t in mapped if any(r.startswith(f"{deck.id}#") for r in t["sources"])]
        while len(current) > 8:
            groups = batches(current, limit=24_000, maximum=16)
            next_topics = []
            for group in groups:
                if len(group) <= 4:
                    next_topics.extend(group)
                    continue
                indexed = [{"id": f"m{i}", **t} for i, t in enumerate(group)]

                def parse(reply, inputs=indexed):
                    result = json_reply(reply, list)
                    if not 1 <= len(result) <= 4:
                        raise ValueError("整合後須有 1–4 個主題")
                    assigned, out = [], []
                    by_id = {t["id"]: t for t in inputs}
                    for item in result:
                        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
                            raise ValueError("整合主題缺標題")
                        explanation = item.get("explanation")
                        if not isinstance(explanation, str) or not explanation.strip() or len(explanation) > 1500:
                            raise ValueError(f"整合解釋需 1–1500 字元，目前 {len(explanation) if isinstance(explanation, str) else 0} 字元；請精簡至 500–800 字元")
                        ids = item.get("topicIds")
                        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in by_id for i in ids):
                            raise ValueError("整合必須引用輸入主題 id")
                        assigned.extend(ids)
                        out.append({"title": item["title"][:120], "explanation": explanation,
                                    "sources": list(dict.fromkeys(r for i in ids for r in by_id[i]["sources"]))})
                    if len(assigned) != len(set(assigned)) or set(assigned) != set(by_id):
                        raise ValueError("整合須保留每個輸入主題一次且僅一次")
                    return out

                next_topics.extend(await checkpoint(ctx, "topic-merge", f"{REDUCE_TASK}\n主題 JSON：{data(indexed)}", MAP_SYSTEM, parse))
                progress(done / max(1, len(ctx.decks)), f"整合核心主題（{deck.title}）")
            # A pathological map whose individual entries exceed the group budget cannot be reduced safely.
            if len(next_topics) >= len(current):
                raise GenerationError("核心主題過長，無法在保留內容的前提下整合")
            current = next_topics
        done += 1
        progress(done / max(1, len(ctx.decks)), f"核心主題整合 {done}/{len(ctx.decks)}")
        return current

    return [t for group in await parallel(ctx.decks, one_deck, config.GEN_CONCURRENCY) for t in group]
