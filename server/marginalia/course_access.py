"""Course-local path checks shared by HTTP entry points and chat tools."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import config
from .store import Course


def confined(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValueError("路徑超出課程範圍") from exc
    return resolved


def check_tree(path: Path, root: Path) -> None:
    """Check directory entries without following directory symlinks."""
    confined(path, root)
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in [*dirs, *files]:
            entry = Path(directory) / name
            if entry.is_symlink():
                confined(entry, root)
                # Search tools may follow an internal alias to a second symlink.
                if entry.is_dir():
                    raise ValueError("不支援資料夾符號連結")


def check_course(course: Course) -> None:
    confined(course.dir, config.COURSES_DIR)
    check_tree(course.dir, course.dir)
    check_manifest(course)


def check_manifest(course: Course) -> None:
    manifest = course.manifest()
    if not isinstance(manifest, dict):
        raise ValueError("教材清單格式不正確")  # noqa: TRY004 - invalid on-disk data
    for kind in ("decks", "videos"):
        items = manifest.get(kind, [])
        if not isinstance(items, list):
            raise ValueError("教材清單格式不正確")  # noqa: TRY004 - invalid on-disk data
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("教材清單格式不正確")  # noqa: TRY004 - invalid on-disk data
            identifier = item.get("id")
            if (
                not isinstance(identifier, str)
                or not re.fullmatch(r"[\w.-]+", identifier)
                or identifier.startswith(".")
            ):
                raise ValueError("教材 ID 格式不正確")
            if "source" in item:
                if not isinstance(item["source"], str):
                    raise ValueError("教材來源路徑不正確")
                confined(course.dir / item["source"], course.materials)
