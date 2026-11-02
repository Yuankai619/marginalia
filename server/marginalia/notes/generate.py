"""Write one markdown note per slide with the local Claude login.

Each slide is one model call that sees the slide image, its text and speaker notes, the neighbouring titles, the
deck outline and the teacher's transcript for the time the slide was on screen. Notes are written atomically as
they finish, so an interrupted run picks up where it stopped. Notes the user edited are never overwritten unless
`force` is set.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path

from .. import config
from ..llm import claude
from ..store import Course
from . import notefile, rules
from .material import Gatherer, Material, render

Progress = Callable[[float, str], None]

STYLE = (Path(__file__).parent / "style.md").read_text("utf-8")
SYSTEM = f"""你是幫作業系統課寫講義的助教。你要把一頁投影片和老師上課講的內容，整理成一份給學生讀的筆記。
下面是寫作規範，每一條都要遵守。

{STYLE}"""

TASK = """## 任務

依照寫作規範，寫第 {index} 頁的筆記。

- 只輸出筆記的 markdown 本文：不要 frontmatter、不要用 ``` 包起來、不要寫頁標題、不要任何前言或說明。
- {links}
- 如果逐字稿顯示老師沒有講這頁（只是翻過去，或這段時間在講別的東西），只輸出一行：`SKIP: <一句說明>`。"""

LINKS_RULE = "時間點連結寫成 [mm:ss](video:<影片 id>?t=<秒數>)，秒數取逐字稿裡講到那件事的那一行開頭的 t 值。"
NO_LINKS_RULE = "這頁沒有逐字稿，所以不要附任何時間點連結；正文只依投影片與講者備註寫，寫不出來的不要猜。"
NOT_SHOWN = "對齊結果裡這頁沒有出現在影片上，老師沒有講解這頁。"
SKIP = re.compile(r"\A\s*SKIP\s*[:：]\s*(.*)", re.DOTALL)
FENCE = re.compile(r"\A```(?:markdown|md)?\s*\n(.*?)\n```\s*\Z", re.DOTALL)


def clean(text: str) -> str:
    """Strip what models wrap around a note anyway: code fences, a frontmatter block, a leading H1."""
    text = text.strip()
    if m := FENCE.match(text):
        text = m.group(1).strip()
    _, text = notefile.parse(text + "\n")
    text = re.sub(r"\A#\s[^\n]*\n+", "", text.strip())
    return rules.normalize_links(text.strip())


def prompt(m: Material) -> str:
    return f"{render(m)}\n\n{TASK.format(index=m.index, links=LINKS_RULE if m.lines else NO_LINKS_RULE)}"


def meta(m: Material, status: str) -> dict:
    return {
        "slide": m.index,
        "title": m.slide.get("title") or f"Slide {m.index}",
        "status": status,
        "sources": notefile.sources(m.ranges),
        "updatedAt": notefile.now(),
    }


def targets(course: Course, deck_id: str, count: int, slides: list[int] | None, force: bool) -> list[int]:
    """Slides to write: missing notes when resuming; the listed ones otherwise; edited notes only with force."""
    out = []
    for i in slides if slides is not None else range(1, count + 1):
        if not 1 <= i <= count:
            raise IndexError(f"slide {i} not in deck {deck_id}")
        existing = notefile.read(course.note_path(deck_id, i))
        if existing is None or force or slides is not None and existing[0].get("status") != "edited":
            out.append(i)
    return out


async def write_note(course: Course, m: Material, aligned: bool, force: bool = False) -> str:
    """Write one slide's note and return its status."""
    path = course.note_path(m.deck["id"], m.index)
    if aligned and not m.ranges:
        status, body = "skipped", NOT_SHOWN
    else:
        call = claude.Call(
            prompt=prompt(m),
            system=SYSTEM,
            images=[m.image] if m.image.exists() else [],
            model=config.WRITER_MODEL,
        )
        out = await claude.complete(call)
        if skip := SKIP.match(out):
            status, body = "skipped", (skip.group(1).strip().splitlines() or [NOT_SHOWN])[0]
        else:
            status, body = "generated", clean(out)
        if not body:
            raise RuntimeError(f"第 {m.index} 頁模型沒有回傳內容")
    notefile.write_unless_edited(path, meta(m, status), body, force)  # the user may have edited it meanwhile
    return status


async def agenerate_deck(
    course: Course, deck_id: str, progress: Progress | None = None, slides: list[int] | None = None, force: bool = False
) -> dict:
    progress = progress or (lambda f, msg: None)
    g = Gatherer(course, deck_id)
    todo = targets(course, deck_id, len(g.slides), slides, force)
    aligned = any(s["deck"] == deck_id for s in course.alignment().get("segments", []))
    result: dict = {"generated": [], "skipped": [], "failed": {}}
    if not todo:
        progress(1.0, "沒有需要產生的筆記")
        return result

    sem = asyncio.Semaphore(max(1, config.GEN_CONCURRENCY))
    done = 0

    async def one(i: int) -> None:
        nonlocal done
        async with sem:
            try:
                status = await write_note(course, g.get(i), aligned, force)
                result["skipped" if status == "skipped" else "generated"].append(i)
            except Exception as e:  # noqa: BLE001 -- one bad slide shouldn't sink the deck; rerun picks it up
                result["failed"][i] = str(e) or type(e).__name__
            done += 1
            progress(done / len(todo), f"筆記 {done}/{len(todo)}（第 {i} 頁）")

    progress(0.0, f"產生 {len(todo)} 頁筆記")
    await asyncio.gather(*(one(i) for i in todo))
    for k in ("generated", "skipped"):
        result[k].sort()
    if result["failed"]:
        pages = "、".join(str(i) for i in sorted(result["failed"]))
        raise RuntimeError(f"第 {pages} 頁產生失敗：{next(iter(result['failed'].values()))}")
    return result


def generate_deck(
    course: Course, deck_id: str, progress: Progress | None = None, slides: list[int] | None = None, force: bool = False
) -> dict:
    """Blocking wrapper for job threads. Returns {generated:[i], skipped:[i], failed:{}}; raises if any slide
    failed, after every other slide has been written."""
    return asyncio.run(agenerate_deck(course, deck_id, progress, slides, force))
