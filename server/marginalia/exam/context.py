"""Everything an exam's generator may read, loaded once from disk, plus the one model call it may make.

The generator (past.py, handout.py, quiz.py) only sees an ExamContext; the shapes are part of the contract in
docs/architecture.md (Exam prep → Generation pipeline interface).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .. import config
from ..llm import claude, codex
from ..notes import notefile
from ..notes.material import MIN_RANGE, PAD, load_transcript
from ..store import Course, slide_name
from .store import Exam

Progress = Callable[[float, str], None]


@dataclass
class SlideDoc:
    deck: str
    index: int
    title: str
    text: str
    speaker_notes: str
    note: str  # note body without frontmatter, "" when there is none
    image: Path | None  # rendered slide image, for llm(images=...)
    lines: list[dict] = field(default_factory=list)  # transcript lines on screen: {video, start, text}


@dataclass
class DeckDoc:
    id: str
    title: str
    slides: list[SlideDoc]


@dataclass
class Upload:
    name: str
    kind: Literal["image", "text"]
    path: Path
    text: str  # content of a text upload, "" for images


@dataclass
class PastQuestion:
    upload: str
    number: str
    type: str
    prompt: str
    options: list[dict] = field(default_factory=list)
    answer_hint: str = ""


@dataclass
class Section:
    title: str
    markdown: str
    sources: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class Engine:
    """Which local login answers: `claude` or a codex account id from GET /api/agents/accounts."""

    account: str = "claude"
    model: str | None = None
    effort: str | None = None


async def call_model(
    engine: Engine, prompt: str, *, system: str = "", images: list[Path] | tuple[Path, ...] = (),
    model: str | None = None,
) -> str:
    """One tool-less call on the user's own login. Material in the prompt may carry injected instructions; with no
    tools they can only change the returned text, which callers parse and validate."""
    model = model or engine.model
    if engine.account == "claude":
        call = claude.Call(prompt=prompt, system=system, images=list(images), model=model or config.WRITER_MODEL,
                           effort=engine.effort, tools=[])  # fmt: skip
        return await claude.complete(call)
    text = f"{system}\n\n{prompt}" if system else prompt
    return await codex.complete(text, codex_home=codex.account_home(engine.account), model=model, images=list(images))


@dataclass
class ExamContext:
    course: Course
    exam: dict
    decks: list[DeckDoc]
    uploads: list[Upload]
    work: Path
    engine: Engine = field(default_factory=Engine)

    async def llm(self, prompt: str, *, system: str = "", images: list[Path] | tuple[Path, ...] = (),
                  model: str | None = None) -> str:  # fmt: skip
        return await call_model(self.engine, prompt, system=system, images=images, model=model)

    def slide_count(self) -> dict[str, int]:
        return {d.id: len(d.slides) for d in self.decks}


def scope_decks(course: Course, exam: dict) -> list[dict]:
    """Decks in scope, in scope order; an empty scope is every visible deck."""
    decks = course.visible_decks()
    wanted = exam.get("scope", {}).get("decks") or []
    if not wanted:
        return decks
    by_id = {d["id"]: d for d in decks}
    return [by_id[d] for d in wanted if d in by_id]


def _slide_lines(course: Course, decks: list[dict], videos: set[str]) -> dict[tuple[str, int], list[dict]]:
    """Transcript lines spoken while each slide was on screen, reading alignment and each transcript once.
    Same windows as notes (material.Gatherer): stretches under MIN_RANGE are dropped unless nothing else is left,
    and lines within PAD seconds of a stretch count."""
    wanted = {d["id"] for d in decks}
    ranges: dict[tuple[str, int], list[dict]] = {}
    for seg in course.alignment().get("segments", []):
        if seg.get("deck") in wanted and seg.get("slide") and (not videos or seg["video"] in videos):
            ranges.setdefault((seg["deck"], seg["slide"]), []).append(seg)
    transcripts: dict[str, list[dict]] = {}
    out = {}
    for key, every in ranges.items():
        lines: list[dict] = []
        for r in [r for r in every if r["end"] - r["start"] >= MIN_RANGE] or every:
            if r["video"] not in transcripts:
                transcripts[r["video"]] = load_transcript(course, r["video"])[0]
            for seg in transcripts[r["video"]]:
                if seg["end"] > r["start"] - PAD and seg["start"] < r["end"] + PAD:
                    line = {"video": r["video"], "start": seg["start"], "text": seg["text"]}
                    if not lines or lines[-1] != line:
                        lines.append(line)
        out[key] = lines
    return out


def load(exam: Exam, engine: Engine | None = None) -> ExamContext:
    course, info = exam.course, exam.info()
    in_scope = scope_decks(course, info)
    lines = _slide_lines(course, in_scope, set(info["scope"].get("videos") or []))
    decks = []
    for deck in in_scope:
        slides = []
        for s in course.slides(deck["id"]):
            index = s["index"]
            note = notefile.read(course.note_path(deck["id"], index))
            image = course.deck_dir(deck["id"]) / "slides" / f"{slide_name(index)}.webp"
            slides.append(SlideDoc(
                deck=deck["id"], index=index, title=s.get("title") or "", text=s.get("text") or "",
                speaker_notes=s.get("speakerNotes") or "", note=note[1] if note else "",
                image=image if image.exists() else None, lines=lines.get((deck["id"], index), []),
            ))  # fmt: skip
        decks.append(DeckDoc(id=deck["id"], title=deck.get("title") or deck["id"], slides=slides))
    uploads = []
    for u in exam.uploads():
        path = exam.upload_path(u["name"])
        text = path.read_text("utf-8", errors="replace") if u["kind"] == "text" else ""
        uploads.append(Upload(name=u["name"], kind=u["kind"], path=path, text=text))
    work = exam.path("work")
    work.mkdir(parents=True, exist_ok=True)
    return ExamContext(course=course, exam=info, decks=decks, uploads=uploads, work=work, engine=engine or Engine())
