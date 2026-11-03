"""On-disk layout of a course and the small helpers that read and write it.

courses/<course>/
  course.json                       title, language, per-video public URLs
  materials/                        raw drops (pptx/pdf/mp4/zip); zips are unpacked to materials/_extracted
  generated/
    manifest.json                   decks and videos found in materials
    decks/<deck>/deck.pdf
    decks/<deck>/slides/001.webp    full-size slide images
    decks/<deck>/thumbs/001.webp
    decks/<deck>/slides.json        per-slide title, text, speaker notes
    videos/<video>/transcript.json  whisper segments
    videos/<video>/frames.npz       sampled-frame fingerprints used for alignment
    alignment.json                  which video time range shows which slide
    reviews/<deck>/001.json         reviewer agents' findings
  notes/<deck>/001.md               the per-slide notes (the thing the user edits)
  chats/<id>.json                   saved agent conversations
  exams/<exam>/                     exam prep: exam.json, uploads/, handout/, quiz.json, attempts/ (exam/store.py)
"""

from __future__ import annotations

import json
import os
import re
import secrets
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

from . import config


def slugify(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"\.[A-Za-z0-9]+$", "", name)
    name = name.replace("&", " and ")
    s = re.sub(r"[^\w]+", "-", name.lower(), flags=re.UNICODE).strip("-_")
    return re.sub(r"-{2,}", "-", s) or "untitled"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def write_text(path: Path, text: str) -> None:
    """Atomic write so a crash never leaves half a note on disk."""
    with atomic_output(path) as output:
        output.write(text.encode("utf-8"))


@contextmanager
def _directory_fd(path: Path, *, create: bool = True) -> Iterator[int]:
    """Pin every parent directory without following symlinks along the way."""
    path = path.absolute()
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def atomic_output(path: Path, *, root: Path | None = None) -> Iterator[BinaryIO]:
    """Create, replace and clean up through one pinned directory descriptor."""
    if path.is_symlink():
        raise ValueError(f"輸出檔案不能是符號連結：{path}")
    destination = Path(os.path.abspath(path))
    # The caller supplies the checked boundary. Never re-resolve it through a
    # replacement symlink; the directory walk below rejects every such link.
    if root is not None and not destination.is_relative_to(Path(os.path.abspath(root))):
        raise ValueError(f"路徑超出允許範圍：{path}")
    with _directory_fd(destination.parent) as directory:
        name = f".tmp-{secrets.token_hex(16)}"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as output:
                identity = os.fstat(output.fileno())
                yield output
                if not os.path.samestat(identity, os.stat(name, dir_fd=directory, follow_symlinks=False)):
                    raise ValueError("暫存檔在寫入期間遭置換")
            os.replace(name, destination.name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass


@contextmanager
def exclusive_output(path: Path, *, root: Path) -> Iterator[BinaryIO]:
    """Create one new file through the same pinned parent walk as atomic_output."""
    destination = Path(os.path.abspath(path))
    if not destination.is_relative_to(Path(os.path.abspath(root))):
        raise ValueError(f"路徑超出允許範圍：{path}")
    with _directory_fd(destination.parent) as directory:
        fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        identity = os.fstat(fd)
        try:
            with os.fdopen(fd, "wb") as output:
                yield output
                if not os.path.samestat(identity, os.stat(destination.name, dir_fd=directory, follow_symlinks=False)):
                    raise ValueError("上傳檔案在寫入期間遭置換")
        except BaseException:
            try:
                if os.path.samestat(identity, os.stat(destination.name, dir_fd=directory, follow_symlinks=False)):
                    os.unlink(destination.name, dir_fd=directory)
            except FileNotFoundError:
                pass
            raise


def unlink_output(path: Path) -> None:
    try:
        with _directory_fd(path.parent, create=False) as directory:
            os.unlink(path.name, dir_fd=directory)
    except FileNotFoundError:
        pass


def slide_name(index: int) -> str:
    if not isinstance(index, int) or index < 1:
        raise ValueError(f"bad slide index: {index!r}")
    return f"{index:03d}"


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\w[\w-]*", value):
        raise ValueError(f"bad id: {value!r}")
    return value


def confined_path(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"路徑超出允許範圍：{path}")
    return resolved


class Course:
    def __init__(self, course_id: str):
        if not re.fullmatch(r"[\w.-]+", course_id) or course_id.startswith("."):
            raise ValueError(f"bad course id: {course_id!r}")
        self.id = course_id
        self._dir = config.COURSES_DIR / course_id

    @property
    def dir(self) -> Path:
        return confined_path(config.COURSES_DIR, self._dir)

    def path(self, *parts: str) -> Path:
        root = self.dir
        if parts and parts[0] in {config.MATERIALS, config.GENERATED, config.NOTES, config.CHATS, config.EXAMS}:
            root = confined_path(root, root / parts[0])
        return confined_path(root, self.dir.joinpath(*parts))

    def source_path(self, source: str) -> Path:
        if Path(source).is_absolute():
            raise ValueError(f"來源必須是相對路徑：{source}")
        return confined_path(self.materials, self.dir / source)

    def fingerprint(self, entry: dict) -> dict:
        stat = self.source_path(entry["source"]).stat()
        return {"source": entry["source"], "size": stat.st_size, "mtimeNs": stat.st_mtime_ns}

    def _validate_manifest(self, manifest: dict) -> dict:
        for entry in manifest["decks"] + manifest["videos"]:
            validate_id(entry["id"])
            self.source_path(entry["source"])
        return manifest

    # paths
    @property
    def materials(self) -> Path:
        return self.path(config.MATERIALS)

    @property
    def gen(self) -> Path:
        return self.path(config.GENERATED)

    @property
    def notes_dir(self) -> Path:
        return self.path(config.NOTES)

    @property
    def chats_dir(self) -> Path:
        return self.path(config.CHATS)

    def deck_path(self, deck: str, *parts: str) -> Path:
        return self.path(config.GENERATED, "decks", validate_id(deck), *parts)

    def video_path(self, video: str, *parts: str) -> Path:
        return self.path(config.GENERATED, "videos", validate_id(video), *parts)

    def video_output_path(self, video: str, name: str) -> Path:
        path = self.video_dir(video) / name
        if path.is_symlink():
            raise ValueError(f"輸出檔案不能是符號連結：{path}")
        return confined_path(self.gen, path)

    def deck_dir(self, deck: str) -> Path:
        return self.deck_path(deck)

    def video_dir(self, video: str) -> Path:
        return self.video_path(video)

    def note_path(self, deck: str, index: int) -> Path:
        return self.path(config.NOTES, validate_id(deck), f"{slide_name(index)}.md")

    def review_path(self, deck: str, index: int) -> Path:
        return self.path(config.GENERATED, "reviews", validate_id(deck), f"{slide_name(index)}.json")

    # metadata
    def exists(self) -> bool:
        return self.dir.is_dir()

    def info(self) -> dict:
        data = read_json(self.path("course.json"), {}) or {}
        data.setdefault("title", self.id.replace("-", " ").title())
        data.setdefault("language", "en+zh-TW")
        data.setdefault("videoUrls", {})
        data.setdefault("hiddenDecks", [])
        data["id"] = self.id
        return data

    def save_info(self, data: dict) -> None:
        data = {k: v for k, v in data.items() if k != "id"}
        write_json(self.path("course.json"), data)

    def manifest(self) -> dict:
        return self._validate_manifest(read_json(self.path(config.GENERATED, "manifest.json"), {"decks": [], "videos": []}))

    def save_manifest(self, m: dict) -> None:
        write_json(self.path(config.GENERATED, "manifest.json"), self._validate_manifest(m))

    def deck(self, deck_id: str) -> dict | None:
        validate_id(deck_id)
        return next((d for d in self.manifest()["decks"] if d["id"] == deck_id), None)

    def video(self, video_id: str) -> dict | None:
        validate_id(video_id)
        return next((v for v in self.manifest()["videos"] if v["id"] == video_id), None)

    def slides(self, deck_id: str) -> list[dict]:
        return read_json(self.deck_path(deck_id, "slides.json"), []) or []

    def transcript(self, video_id: str) -> dict | None:
        return read_json(self.video_path(video_id, "transcript.json"))

    def transcript_current(self, video_id: str) -> bool:
        transcript = self.transcript(video_id)
        return bool(transcript and transcript.get("sourceFingerprint") == self.fingerprint(self.video(video_id)))

    def alignment(self) -> dict:
        return read_json(self.path(config.GENERATED, "alignment.json"), {"segments": []})

    def status(self) -> dict:
        return read_json(self.path(config.GENERATED, "status.json"), {}) or {}

    def set_status(self, key: str, value: dict) -> None:
        s = self.status()
        s[key] = value
        write_json(self.path(config.GENERATED, "status.json"), s)


def list_courses() -> list[Course]:
    if not config.COURSES_DIR.is_dir():
        return []
    out = []
    for p in sorted(config.COURSES_DIR.iterdir()):
        if p.is_dir() and not p.name.startswith(".") and (
            (p / config.MATERIALS).is_dir() or (p / "course.json").exists()
        ):
            out.append(Course(p.name))
    return out
