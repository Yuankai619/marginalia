"""The local, resumable course-processing pipeline."""

from __future__ import annotations

from collections.abc import Callable

from . import align, ingest, slides, transcribe
from .store import Course

Progress = Callable[[float, str], None]


def _step(progress: Progress, start: float, size: float, label: str) -> Progress:
    return lambda fraction, message: progress(start + size * fraction, f"{label}：{message}")


def process(course: Course, decks: list[str] | None = None, progress: Progress = lambda f, m: None) -> dict:
    """Scan, render, align, transcribe and generate notes for a course.

    Rendering and transcription are deliberately resumable: their existing
    outputs are left alone.  Alignment is cheap enough to refresh for every
    run, so all course videos are considered even when notes are requested for
    a single deck.
    """
    progress(0.0, "掃描教材")
    manifest = ingest.scan(course)
    selected = decks or [deck["id"] for deck in manifest["decks"]]
    known = {deck["id"] for deck in manifest["decks"]}
    missing = set(selected) - known
    if missing:
        raise KeyError(f"找不到簡報：{', '.join(sorted(missing))}")

    render_progress = _step(progress, 0.05, 0.3, "轉出投影片")
    to_render = [
        deck
        for deck in selected
        if not (course.deck(deck) or {}).get("rendered") or not (course.deck_dir(deck) / "slides.json").exists()
    ]
    for index, deck in enumerate(to_render):
        render_progress(index / max(len(to_render), 1), f"準備 {deck}")
        slides.render_deck(
            course,
            deck,
            _step(render_progress, index / max(len(to_render), 1), 1 / max(len(to_render), 1), deck),
        )
    render_progress(1.0, "完成")

    alignment = align.align_course(course, _step(progress, 0.35, 0.25, "對齊影片"))
    target_videos = {
        segment["video"]
        for segment in alignment["segments"]
        if segment.get("deck") in selected
    }
    to_transcribe = [
        video["id"]
        for video in manifest["videos"]
        if video["id"] in target_videos and not (course.video_dir(video["id"]) / "transcript.json").exists()
    ]
    transcription_progress = _step(progress, 0.6, 0.25, "轉錄影片")
    for index, video in enumerate(to_transcribe):
        transcribe.transcribe_video(
            course,
            video,
            _step(
                transcription_progress,
                index / max(len(to_transcribe), 1),
                1 / max(len(to_transcribe), 1),
                video,
            ),
        )
    transcription_progress(1.0, "完成")

    generated: list[str] = []
    try:
        from .notes.generate import generate_deck
    except ImportError:
        progress(0.9, "筆記產生模組尚未安裝，已跳過")
    else:
        notes_progress = _step(progress, 0.85, 0.15, "產生筆記")
        for index, deck in enumerate(selected):
            generate_deck(
                course,
                deck,
                _step(notes_progress, index / max(len(selected), 1), 1 / max(len(selected), 1), deck),
            )
            generated.append(deck)
    progress(1.0, "處理完成")
    return {
        "decks": selected,
        "rendered": to_render,
        "transcribed": to_transcribe,
        "generated": generated,
    }
