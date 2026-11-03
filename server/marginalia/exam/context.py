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
from ..notes.material import Gatherer
from ..store import Course
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
    home = Path.home() / (".codex" if engine.account == "codex" else f".{engine.account}")
    text = f"{system}\n\n{prompt}" if system else prompt
    return await codex.complete(text, codex_home=home, model=model, images=list(images))


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
    hidden = set(course.info().get("hiddenDecks") or [])
    decks = [d for d in course.manifest()["decks"] if d["id"] not in hidden and not d.get("hidden")]
    wanted = exam.get("scope", {}).get("decks") or []
    if not wanted:
        return decks
    by_id = {d["id"]: d for d in course.manifest()["decks"]}
    return [by_id[d] for d in wanted if d in by_id]


def load(exam: Exam, engine: Engine | None = None) -> ExamContext:
    course, info = exam.course, exam.info()
    videos = set(info["scope"].get("videos") or [])
    decks = []
    for deck in scope_decks(course, info):
        g = Gatherer(course, deck["id"])
        slides = []
        for s in g.slides:
            m = g.get(s["index"])
            note = notefile.read(course.note_path(deck["id"], s["index"]))
            lines = [ln for ln in m.lines if not videos or ln["video"] in videos]
            slides.append(SlideDoc(
                deck=deck["id"], index=s["index"], title=s.get("title") or "", text=s.get("text") or "",
                speaker_notes=s.get("speakerNotes") or "", note=note[1] if note else "",
                image=m.image if m.image.exists() else None, lines=lines,
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
