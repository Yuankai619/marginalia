"""The `exam` job: build the context, run the generator parts, validate and write their output.

Generators (past.py, handout.py, quiz.py) never write handout/, quiz.json or attempts/; this module does, after
checking every section and question against the contract (docs/architecture.md, Exam prep).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from ..notes import notefile
from ..notes.rules import normalize_links
from ..store import Course, unlink_output
from . import context, handout, past, quiz, schema
from .context import Engine, PastQuestion, Section
from .grade import normalize
from .store import Exam

PARTS = ("handout", "quiz")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]*)\)")


class ExamError(RuntimeError):
    """A job failure whose message is safe to show the user."""


def fix_images(markdown: str, exam: Exam, decks: dict[str, int]) -> str:
    """Keep `slide:` images of real slides and `assets/` images that exist; the rest become their caption."""

    def keep(m: re.Match[str]) -> str:
        caption, src = m[1], m[2]
        if (s := re.fullmatch(r"slide:([\w][\w-]*)/(\d+)", src)) and 1 <= int(s[2]) <= decks.get(s[1], 0):
            return m[0]
        a = re.fullmatch(r"assets/([\w][\w.-]*)", src)
        if a and ".." not in a[1] and (exam.dir / "handout" / "assets" / a[1]).is_file():
            return m[0]
        return f"［圖：{caption}］" if caption else ""

    return _IMAGE.sub(keep, markdown)


def _key(text: str) -> str:
    return normalize(re.sub(r"[\W_]+", "", text))[:20]


def _past_question(p: PastQuestion) -> dict:
    """A past-paper question the quiz writer left out: kept as a short-answer question with no rubric."""
    return {"type": "short", "origin": "past", "pastRef": p.upload, "prompt": p.prompt, "points": 6,
            "topic": f"考古題 {p.number}".strip()}  # fmt: skip


def write_sections(exam: Exam, sections: list[Section], decks: dict[str, int], force: bool) -> str:
    """Replace the handout unless the user edited any section meanwhile. Returns `written` or `kept`."""
    existing = exam.section_numbers()
    edited = {n for n in existing if (s := exam.section(n)) is not None and notefile.protected(s[0])}
    if edited and not force:
        return "kept"
    for n, section in enumerate(sections, 1):
        path = exam.section_path(n)
        meta = {"section": n, "title": section.title, "status": "generated",
                "sources": [f"{d}#{i}" for d, i in section.sources if 1 <= i <= decks.get(d, 0)],
                "updatedAt": notefile.now()}  # fmt: skip
        body = fix_images(normalize_links(section.markdown), exam, decks)
        if not notefile.commit(path, meta, body, notefile.version(path), force=force):
            raise ExamError(f"第 {n} 節在產生期間被修改，已保留你的版本")
    for n in existing:
        if n > len(sections) and n not in edited:
            unlink_output(exam.section_path(n))
    return "written"


def clean_quiz(exam: Exam, raw: list[dict], past_questions: list[PastQuestion], decks: dict[str, int]) -> tuple[list[dict], int]:
    """Validated questions (past-paper ones first) and how many were dropped."""
    questions = [q for q in (schema.clean_question(q, decks) for q in raw) if q]
    dropped = len(raw) - len(questions)
    # The quiz writer must keep every past-paper question; put back any it left out (matched on the prompt's start).
    covered = {(q.get("pastRef"), _key(q["prompt"])) for q in questions if q["origin"] == "past"}
    for p in past_questions:
        if (p.upload, _key(p.prompt)) not in covered:
            questions.append(schema.clean_question(_past_question(p), decks))
            covered.add((p.upload, _key(p.prompt)))
    for q in questions:
        for key in ("prompt", "solution"):
            if q.get(key):
                q[key] = fix_images(q[key], exam, decks)
    questions.sort(key=lambda q: q["origin"] != "past")  # stable: past papers first, in their order
    return schema.number(questions), dropped


async def agenerate(course: Course, exam_id: str, *, parts: list[str] | None = None, force: bool = False,
                    engine: Engine | None = None, progress: Callable[[float, str], None] | None = None) -> str:  # fmt: skip
    progress = progress or (lambda f, m: None)
    exam = Exam(course, exam_id)
    if not exam.exists():
        raise ExamError("找不到考試")
    parts = [p for p in PARTS if p in (parts or PARTS)]
    if not parts:
        raise ExamError("沒有指定要產生的內容")
    ctx = await asyncio.to_thread(context.load, exam, engine)
    if not ctx.decks:
        raise ExamError("考試範圍沒有任何簡報")
    decks = ctx.slide_count()
    # Weights of each step in the job's progress bar.
    plan = ([("past", 0.15)] if "quiz" in parts and ctx.uploads else []) + [(p, 0.6 if p == "handout" else 0.3) for p in parts]
    total = sum(w for _, w in plan)
    offset = 0.0

    def step(weight: float) -> Callable[[float, str], None]:
        start = offset
        return lambda f, m: progress((start + weight * max(0.0, min(1.0, f))) / total, m)

    messages = []
    past_questions: list[PastQuestion] = []
    for name, weight in plan:
        report = step(weight)
        if name == "past":
            past_questions = await past.parse_uploads(ctx, report)
        elif name == "handout":
            sections = await handout.write_handout(ctx, report)
            if not sections:
                raise ExamError("模型沒有寫出任何講義段落")
            if write_sections(exam, sections, decks, force) == "kept":
                messages.append("講義已有你編輯過的段落，未覆寫")
            else:
                messages.append(f"講義 {len(sections)} 節")
        else:
            raw = await quiz.write_quiz(ctx, past_questions, report)
            questions, dropped = clean_quiz(exam, raw, past_questions, decks)
            if not questions:
                raise ExamError("模型沒有產生任何有效題目")
            exam.save_quiz(questions)
            messages.append(f"題目 {len(questions)} 題" + (f"（略過 {dropped} 題格式不符）" if dropped else ""))
        offset += weight
    return "、".join(messages)


def generate_exam(course: Course, exam_id: str, **kwargs) -> str:
    """Blocking wrapper for job threads; returns the job's completion message."""
    return asyncio.run(agenerate(course, exam_id, **kwargs))
