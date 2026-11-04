"""Full, source-addressed evidence for semantic checks; excerpts are never proof."""

from __future__ import annotations

from .context import ExamContext
from .generation import batches, slide_data
from .grade import normalize


def full_material(ctx: ExamContext, refs: list[str]) -> list[dict]:
    by_ref = {f"{s.deck}#{s.index}": s for d in ctx.decks for s in d.slides}
    if any(r not in by_ref for r in refs):
        raise ValueError("核對來源不在考試範圍內")
    return [slide_data(by_ref[r]) for r in dict.fromkeys(refs)]


def source_batches(ctx: ExamContext, refs: list[str]) -> list[list[dict]]:
    return batches(full_material(ctx, refs), limit=24_000, maximum=8)


def images_for(ctx: ExamContext, originals: list[dict]) -> dict:
    wanted = {s["source"] for s in originals}
    return {f"{s.deck}#{s.index}": s.image for d in ctx.decks for s in d.slides
            if f"{s.deck}#{s.index}" in wanted and s.image is not None}


def proof(item: dict, originals: list[dict], image_sources=()) -> None:
    by_ref = {s["source"]: s for s in originals}
    if not isinstance(item, dict) or item.get("source") not in by_ref:
        raise ValueError("核對必須引用本批完整來源")
    if item.get("kind") == "image":
        if item["source"] not in image_sources or not isinstance(item.get("observation"), str) or not item["observation"].strip():
            raise ValueError("圖片證據必須附實際提供圖片的具體觀察")
        return
    quote = item.get("quote")
    original = by_ref[item["source"]]
    fields = [original[k] for k in ("title", "text", "speakerNotes", "note")]
    fields += [line["text"] for line in original["transcript"]]
    if not isinstance(quote, str) or not quote.strip() or not any(normalize(quote) in normalize(t) for t in fields):
        raise ValueError("核對證據必須逐字引用完整來源，不可引用摘要或改寫")
