"""Full, source-addressed evidence for semantic checks; excerpts are never proof."""

from __future__ import annotations

import html
import re

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


def quote_key(text: str) -> str:
    """Ignore presentation markup, never mathematical operators, variables or numbers."""
    text = html.unescape(text)
    text = re.sub(r"!?\[([^]\n]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"(?<!\w)(\*\*|__)(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", text)
    text = re.sub(r"\\([*_`\[\]])", r"\1", text)
    return normalize(text)


def evidence_refs(item: dict) -> list[str]:
    return list(dict.fromkeys([item["source"], *[s["source"] for s in item.get("sources", [])]]))


def proof(item: dict, originals: list[dict], image_sources=()) -> None:
    """Accept flat or evidence-array shapes, strictly validating every supplied source."""
    if not isinstance(item, dict):
        raise TypeError("證據須為物件：source/quote，或 sources:[{source,quote}]")
    records = []
    if 'source' in item:
        records.append(item)
    nested = item.get('sources', [])
    if not isinstance(nested, list) or any(not isinstance(r, dict) for r in nested):
        raise ValueError('sources 須為證據物件陣列，例如 sources:[{"source":"deck#1","kind":"text","quote":"原文"}]')
    records.extend(nested)
    if not records:
        raise ValueError('缺少證據欄位，需 source/quote 或 sources:[{"source":"deck#1","quote":"原文"}]')
    by_ref = {s['source']: s for s in originals}
    for index, record in enumerate(records):
        source = record.get('source')
        if not isinstance(source, str) or source not in by_ref:
            raise ValueError(f"證據 {index + 1} source 必須引用本批完整來源：{', '.join(by_ref)}")
        if record.get('kind') == 'image':
            if source not in image_sources or not isinstance(record.get('observation'), str) or not record['observation'].strip():
                raise ValueError(f'{source} 圖片證據須引用實際附圖並提供具體 observation')
            continue
        original = by_ref[source]
        fields = [original[k] for k in ('title', 'text', 'speakerNotes', 'note')]
        fields += [line['text'] for line in original['transcript']]
        raw = record.get('quote')
        quotes = raw if isinstance(raw, list) else [raw]
        if not quotes or any(not isinstance(q, str) or not quote_key(q) or not any(quote_key(q) in quote_key(t) for t in fields) for q in quotes):
            raise ValueError(f'{source} quote 必須逐字引用完整來源（可忽略 Markdown 樣式），不得改公式／數字或用省略號拼接；多段原文可用 quote 字串陣列')
    if 'source' not in item:
        for key in ('source', 'kind', 'quote', 'observation'):
            if key in records[0]:
                item[key] = records[0][key]
