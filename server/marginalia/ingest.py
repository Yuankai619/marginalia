"""Scan a course's materials folder and register every deck and video.

Users can drop anything into materials/: loose pptx/pdf/mp4 files, sub-folders,
or the zip files a course platform hands out. Zips are unpacked once into
materials/_extracted/<zip name>/.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path

from . import config, media
from .store import Course, confined_path, slugify

DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)"), lambda m: (2000 + int(m[1]), int(m[2]), int(m[3]))),
]


def guess_date(name: str, fallback: float) -> str:
    for pat, conv in DATE_PATTERNS:
        for m in pat.finditer(name):
            y, mo, d = conv(m)
            try:
                return datetime(y, mo, d).date().isoformat()
            except ValueError:
                continue
    return datetime.fromtimestamp(fallback).date().isoformat()


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if Path(member.filename).is_absolute() or not target.is_relative_to(root):
            raise RuntimeError(f"zip 內有不安全的路徑：{member.filename}")
    zf.extractall(dest)


def unpack_zips(course: Course) -> list[str]:
    done = []
    for z in sorted(course.materials.rglob("*.zip")):
        z = confined_path(course.materials, z)
        if "_extracted" in z.parts:
            continue
        dest = course.path(config.MATERIALS, "_extracted", z.stem)
        if dest.exists():
            continue
        with zipfile.ZipFile(z) as zf:
            _safe_extract(zf, dest)
        done.append(z.name)
    return done


def _unique(base: str, taken: set[str]) -> str:
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    taken.add(out)
    return out


def scan(course: Course) -> dict:
    course.materials.mkdir(parents=True, exist_ok=True)
    unpack_zips(course)
    old = course.manifest()
    old_by_src = {e["source"]: e for e in old["decks"] + old["videos"]}

    decks, videos = [], []
    taken: set[str] = set()
    files = []
    for path in course.materials.rglob("*"):
        course.source_path(str(path.relative_to(course.dir)))
        if path.is_file() and not any(part.startswith(".") for part in path.parts):
            files.append(path)
    for p in sorted(files, key=lambda p: natural_key(p.name)):
        ext = p.suffix.lower()
        rel = str(p.relative_to(course.dir))
        p = course.source_path(rel)
        prev = old_by_src.get(rel, {})
        if ext in config.DECK_EXTS:
            if p.name.startswith("~$"):
                continue  # PowerPoint lock file
            entry = {
                "id": prev.get("id") or _unique(slugify(p.stem), taken),
                "title": prev.get("title") or p.stem,
                "source": rel,
                "date": guess_date(p.stem, p.stat().st_mtime),
                "size": p.stat().st_size,
                "mtimeNs": p.stat().st_mtime_ns,
            }
            taken.add(entry["id"])
            for k in ("slideCount", "width", "height", "rendered"):
                if k in prev and all(prev.get(key) == entry[key] for key in ("size", "mtimeNs")):
                    entry[k] = prev[k]
            decks.append(entry)
        elif ext in config.VIDEO_EXTS or ext in config.AUDIO_EXTS:
            entry = {
                "id": prev.get("id") or _unique(slugify(p.stem), taken),
                "title": prev.get("title") or p.stem,
                "source": rel,
                "date": guess_date(p.stem, p.stat().st_mtime),
                "size": p.stat().st_size,
                "mtimeNs": p.stat().st_mtime_ns,
                "kind": "audio" if ext in config.AUDIO_EXTS else "video",
            }
            taken.add(entry["id"])
            unchanged = all(prev.get(key) == entry[key] for key in ("size", "mtimeNs"))
            entry["duration"] = prev.get("duration") if unchanged and prev.get("duration") else round(media.duration(p), 2)
            videos.append(entry)

    decks.sort(key=lambda d: natural_key(d["title"]))
    videos.sort(key=lambda v: (v["date"], natural_key(v["title"])))
    man = {"decks": decks, "videos": videos}
    course.save_manifest(man)
    return man
