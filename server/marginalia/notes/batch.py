"""Shared plumbing for per-slide deck jobs: picking the slides to touch and running them with progress."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..store import Course
from . import notefile

Progress = Callable[[float, str], None]


def select(course: Course, deck_id: str, count: int, slides: list[int] | None, keep: Callable[[int, dict | None], bool]) -> list[int]:
    """The listed slides (or all of them) for which `keep(index, frontmatter)` holds; frontmatter is None when there
    is no note."""
    out = []
    for i in slides if slides is not None else range(1, count + 1):
        if not 1 <= i <= count:
            raise IndexError(f"slide {i} not in deck {deck_id}")
        note = notefile.read(course.note_path(deck_id, i))
        if keep(i, note[0] if note else None):
            out.append(i)
    return out


async def run_slides[T](todo: list[int], work: Callable[[int], Awaitable[T]], label: str, progress: Progress) -> dict[int, T]:
    """Run `work` for every slide concurrently and return results by slide. One failing slide doesn't stop the rest;
    after all are done, any failure is raised so the job shows as failed and a rerun picks those slides up."""
    results: dict[int, T] = {}
    failed: dict[int, str] = {}

    async def one(i: int) -> None:
        try:
            results[i] = await work(i)
        except Exception as e:  # noqa: BLE001 -- reported per slide, the rest carry on
            failed[i] = str(e) or type(e).__name__
        done = len(results) + len(failed)
        progress(done / len(todo), f"{label} {done}/{len(todo)}（第 {i} 頁）")

    await asyncio.gather(*(one(i) for i in todo))
    if failed:
        pages = "、".join(str(i) for i in sorted(failed))
        raise RuntimeError(f"第 {pages} 頁{label}失敗：{failed[min(failed)]}")
    return dict(sorted(results.items()))
