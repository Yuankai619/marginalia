"""Read and write `notes/<deck>/NNN.md`: YAML frontmatter + markdown body (format in docs/architecture.md)."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

from ..store import write_text

_FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


def parse(text: str) -> tuple[dict, str]:
    m = _FRONT.match(text)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    return (meta if isinstance(meta, dict) else {}), text[m.end() :].strip("\n")


def dump(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body.strip()}\n"


def read(path: Path) -> tuple[dict, str] | None:
    try:
        return parse(path.read_text("utf-8"))
    except FileNotFoundError:
        return None


def protected(meta: dict) -> bool:
    """Whether a note belongs to the user. A note without a status counts as edited: hand-written files are safe."""
    return meta.get("status", "edited") == "edited"


def version(path: Path) -> str | None:
    """Hash of the file as it is on disk now, or None when it doesn't exist."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def digest(body: str) -> str:
    """Hash of a note body, used to tie a review record to the text it is about."""
    return hashlib.sha256(body.strip().encode()).hexdigest()[:16]


def write(path: Path, meta: dict, body: str) -> None:
    with locked(path):
        write_text(path, dump(meta, body))


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Serialize check-then-write on one deck's notes across threads and processes. The lock is flock on the deck's
    notes folder itself, so no lock file lands among the user's notes. Held only around disk access, never across a
    model call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing releases the lock


def commit(path: Path, meta: dict, body: str, expected: str | None, force: bool = False) -> bool:
    """Compare-and-swap. Write only if the file is still the version this job started from (`expected`, None for
    absent) and, unless `force`, not the user's. Anything else wrote it meanwhile (the user, another job): their
    version wins and this returns False."""
    with locked(path):
        if version(path) != expected:
            return False
        current = read(path)
        if not force and current is not None and protected(current[0]):
            return False
        write_text(path, dump(meta, body))
        return True


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sources(ranges: list[dict]) -> list[str]:
    return [f"{r['video']}@{r['start']:.0f}-{r['end']:.0f}" for r in ranges]
