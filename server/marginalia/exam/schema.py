"""Quiz question validation (shape in docs/architecture.md, Exam prep → quiz.json).

Generators return loosely shaped dicts from model output; `clean_question` keeps only the contract's fields, fixes
what is safe to fix (types, numbering, option ids) and returns None for anything a student could not answer.
"""

from __future__ import annotations

import json
import re
from typing import Any

TYPES = ("choice", "fill", "short", "essay", "calc")
OBJECTIVE = {"choice", "fill"}
SUBJECTIVE = {"short", "essay", "calc"}
MAX_TEXT = 8_000
ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
BLANK = re.compile(r"\{\{(\d+)\}\}")
OPTION_IDS = "ABCDEFGH"


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _points(value: Any, default: int) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return default
    return max(1, min(100, number))


def _sources(value: Any, decks: dict[str, int] | None) -> list[dict]:
    out = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("deck"), str):
            continue
        try:
            slide = int(item.get("slide"))
        except (TypeError, ValueError):
            continue
        if decks is not None and not 1 <= slide <= decks.get(item["deck"], 0):
            continue
        out.append({"deck": item["deck"], "slide": slide})
    return out[:10]


def clean_question(q: Any, decks: dict[str, int] | None = None) -> dict | None:
    """A question in the quiz.json shape, or None. `decks` maps deck id → slide count to drop stray sources."""
    if not isinstance(q, dict) or q.get("type") not in TYPES:
        return None
    kind = q["type"]
    prompt = _text(q.get("prompt"))
    if not prompt:
        return None
    out: dict[str, Any] = {"id": q["id"] if isinstance(q.get("id"), str) and ID.fullmatch(q["id"]) else "",
                           "type": kind, "origin": "past" if q.get("origin") == "past" else "new"}
    if out["origin"] == "past" and isinstance(q.get("pastRef"), str):
        out["pastRef"] = q["pastRef"][:120]
    out["prompt"] = prompt
    if kind == "choice":
        options = [o for o in q.get("options") or [] if isinstance(o, dict) and _text(o.get("text"))][:8]
        if len(options) < 2:
            return None
        # Renumber A, B, … and carry the answer over by the old ids (models sometimes write "a" or "(A)").
        old = [str(o.get("id", "")).strip("() .").upper() for o in options]
        answer = {str(a).strip("() .").upper() for a in q.get("answer") or [] if isinstance(a, str | int)}
        out["options"] = [{"id": OPTION_IDS[i], "text": _text(o["text"], 2_000)} for i, o in enumerate(options)]
        out["answer"] = [OPTION_IDS[i] for i, o in enumerate(old) if o in answer]
        if not out["answer"]:
            return None
        out["multiple"] = bool(q.get("multiple")) or len(out["answer"]) > 1
    elif kind == "fill":
        numbers = sorted({int(n) for n in BLANK.findall(prompt)})
        blanks = [[_text(a, 200) for a in b if _text(a, 200)] for b in q.get("blanks") or [] if isinstance(b, list)]
        if not numbers or numbers != list(range(1, len(numbers) + 1)) or len(blanks) < len(numbers):
            return None
        blanks = blanks[: len(numbers)]
        if not all(blanks):
            return None
        out["blanks"] = blanks
    out["points"] = _points(q.get("points"), 2 if kind in OBJECTIVE else 6)
    solution = _text(q.get("solution"))
    if solution:
        out["solution"] = solution
    if kind in SUBJECTIVE:
        rubric = []
        for item in q.get("rubric") or []:
            if isinstance(item, dict) and _text(item.get("point"), 1_000):
                rubric.append({"point": _text(item["point"], 1_000), "points": _points(item.get("points"), 1)})
        if rubric:
            out["rubric"] = rubric[:12]
            out["points"] = sum(r["points"] for r in out["rubric"])
    sources = _sources(q.get("sources"), decks)
    if sources:
        out["sources"] = sources
    if _text(q.get("topic"), 80):
        out["topic"] = _text(q["topic"], 80)
    return out


def number(questions: list[dict]) -> list[dict]:
    """Ids q1, q2, … in quiz order; attempts are tied to one quiz version by its hash, not to generator ids."""
    for n, q in enumerate(questions, 1):
        q["id"] = f"q{n}"
    return questions


def json_reply(text: str, kind: type[dict | list]) -> Any:
    """The JSON object or array in a model reply, tolerating a code fence or a sentence around it."""
    text = text.strip()
    if m := re.match(r"\A```(?:json)?\s*\n(.*)\n```\s*\Z", text, re.DOTALL):
        text = m[1]
    start, end = text.find("{[" [kind is list]), text.rfind("}]" [kind is list])
    if start < 0 or end < start:
        raise ValueError("模型回覆不是 JSON")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, kind):
        raise ValueError("模型回覆的 JSON 格式不對")  # noqa: TRY004 - callers treat every bad reply alike
    return data
