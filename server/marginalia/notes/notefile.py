"""Read and write `notes/<deck>/NNN.md`: YAML frontmatter + markdown body (format in docs/architecture.md)."""

from __future__ import annotations

import fcntl
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


def write(path: Path, meta: dict, body: str) -> None:
    with locked(path):
        write_text(path, dump(meta, body))


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Serialize check-then-write on one deck's notes across threads and processes. The lock is flock on the deck's
    notes folder itself, so no lock file lands among the user's notes. `write` takes it; so does the check in
    `write_unless_edited`, which is how a note the user just saved is never replaced by a generated one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing releases the lock


def write_unless_edited(path: Path, meta: dict, body: str, force: bool = False) -> bool:
    """Write the note unless the user has edited it (re-checked under the lock). Returns whether it was written."""
    with locked(path):
        current = read(path)
        if not force and current is not None and current[0].get("status") == "edited":
            return False
        write_text(path, dump(meta, body))
        return True


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sources(ranges: list[dict]) -> list[str]:
    return [f"{r['video']}@{r['start']:.0f}-{r['end']:.0f}" for r in ranges]
