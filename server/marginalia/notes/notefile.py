"""Read and write `notes/<deck>/NNN.md`: YAML frontmatter + markdown body (format in docs/architecture.md)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

from ..store import write_text

STATUSES = ("generated", "reviewed", "edited", "skipped")
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
    write_text(path, dump(meta, body))


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sources(ranges: list[dict]) -> list[str]:
    return [f"{r['video']}@{r['start']:.0f}-{r['end']:.0f}" for r in ranges]
