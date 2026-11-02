"""A tiny generated course for the notes and chat-prompt tests: one 3-slide deck, one video, an alignment and a
transcript. No real course content. Overrides the empty `course` fixture from tests/conftest.py."""

from __future__ import annotations

import pytest

from marginalia import config
from marginalia.store import Course, write_json

SLIDES = [
    {"index": 1, "title": "Intro", "text": "Intro\nWhy kernels exist", "speakerNotes": ""},
    {"index": 2, "title": "System Calls", "text": "System Calls\nUser mode -> kernel mode", "speakerNotes": "Explain traps."},
    {"index": 3, "title": "Backup Slide", "text": "Backup", "speakerNotes": ""},
]
TRANSCRIPT = [
    {"start": 2.0, "end": 8.0, "text": "today we talk about the kernel"},
    {"start": 30.0, "end": 36.0, "text": "the kernel manages hardware"},
    {"start": 64.0, "end": 70.0, "text": "a system call is like a door into the kernel"},
    {"start": 90.0, "end": 96.0, "text": "the CPU switches to kernel mode"},
    {"start": 200.0, "end": 206.0, "text": "unrelated chat after class"},
]


@pytest.fixture
def course(tmp_path, monkeypatch) -> Course:
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    c = Course("demo")
    write_json(c.dir / "course.json", {"title": "Demo OS", "hiddenDecks": []})
    c.save_manifest(
        {
            "decks": [{"id": "d1", "title": "L1 Demo", "source": "materials/d1.pptx", "date": "2026-09-16", "slideCount": 3}],
            "videos": [{"id": "v1", "source": "materials/v1.mp4", "duration": 300}],
        }
    )
    write_json(c.deck_dir("d1") / "slides.json", SLIDES)
    write_json(
        c.gen / "alignment.json",
        {
            "segments": [
                {"video": "v1", "start": 0.0, "end": 60.0, "deck": "d1", "slide": 1, "score": 0.9, "manual": False},
                {"video": "v1", "start": 60.0, "end": 120.0, "deck": "d1", "slide": 2, "score": 0.9, "manual": False},
                {"video": "v1", "start": 120.0, "end": 300.0, "deck": None, "slide": None, "score": 0.0, "manual": False},
            ]
        },
    )
    write_json(c.video_dir("v1") / "transcript.json", {"segments": TRANSCRIPT})
    return c
