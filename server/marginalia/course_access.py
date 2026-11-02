"""Course-local path checks shared by HTTP entry points and chat tools."""

from __future__ import annotations

import os
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
