"""Paths and settings. Everything lives on disk under the repo; no database."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("MARGINALIA_ROOT", Path(__file__).resolve().parents[2]))
COURSES_DIR = Path(os.environ.get("MARGINALIA_COURSES", ROOT / "courses"))

# Folder names inside a course
MATERIALS = "materials"  # raw drops: pptx / pdf / mp4 / zip
GENERATED = "generated"  # everything the pipeline can rebuild
NOTES = "notes"  # per-slide markdown, the user's editable output
CHATS = "chats"
EXAMS = "exams"  # exam prep: handout, quiz, attempts per exam

SLIDE_WIDTH = 1600  # rendered slide width in px
THUMB_WIDTH = 320

DECK_EXTS = {".pptx", ".ppt", ".pdf", ".key", ".odp"}
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav"}

WHISPER_MODEL = os.environ.get("MARGINALIA_WHISPER_MODEL", "large-v3-turbo")
WHISPER_THREADS = int(os.environ.get("MARGINALIA_WHISPER_THREADS", max(1, (os.cpu_count() or 4) - 2)))

# Model aliases resolved by Claude Code itself, so they never go stale.
WRITER_MODEL = os.environ.get("MARGINALIA_WRITER_MODEL", "opus")
REVIEW_MODEL = os.environ.get("MARGINALIA_REVIEW_MODEL", "sonnet")
CHAT_MODEL = os.environ.get("MARGINALIA_CHAT_MODEL", "sonnet")
GEN_CONCURRENCY = int(os.environ.get("MARGINALIA_GEN_CONCURRENCY", "4"))
