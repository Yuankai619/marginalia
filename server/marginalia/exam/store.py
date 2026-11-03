"""`courses/<c>/exams/<exam>/`: settings, past-paper uploads, handout sections, quiz and attempts.

The layout and every JSON shape are in docs/architecture.md (Exam prep). Paths go through `Course.path`, so they
stay inside the course; files are written with the store's pinned-directory helpers.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

from .. import config, note_assets
from ..notes import notefile
from ..store import (
    Course,
    exclusive_output,
    read_json,
    slugify,
    unlink_output,
    validate_id,
    write_json,
    write_text,
)

MAX_UPLOADS = 40
MAX_TEXT_BYTES = 1024 * 1024
MAX_PASTE_CHARS = 200_000
IMAGE_TYPES = {"png", "jpg", "webp"}
TEXT_TYPES = {"txt", "md"}
_NAME = re.compile(r"[\w][\w.-]*")
_ATTEMPT = re.compile(r"[a-f0-9]{32}")
_SECTION = re.compile(r"(\d{3})\.md")


class UploadError(ValueError):
    """A problem with an uploaded file itself; the message is safe to show the user."""


class UploadTooLarge(UploadError):
    pass


def now() -> str:
    return notefile.now()


def section_name(n: int) -> str:
    if not isinstance(n, int) or not 1 <= n <= 999:
        raise ValueError(f"bad section: {n!r}")
    return f"{n:03d}.md"


def upload_name(name: str) -> str:
    """A name as it may appear in a URL or quiz `pastRef`: one flat file, no traversal."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or ".." in name:
        raise ValueError(f"bad upload name: {name!r}")
    return name


class Exam:
    def __init__(self, course: Course, exam_id: str):
        self.course = course
        self.id = validate_id(exam_id)

    @property
    def dir(self) -> Path:
        return self.course.path(config.EXAMS, self.id)

    def path(self, *parts: str) -> Path:
        return self.course.path(config.EXAMS, self.id, *parts)

    def exists(self) -> bool:
        return (self.dir / "exam.json").is_file()

    def locked(self):
        """Serialize read-modify-write of exam.json and uploads: flock on the exam folder, like notes."""
        return notefile.locked(self.path("exam.json"))

    # settings
    def info(self) -> dict:
        data = read_json(self.path("exam.json"), {}) or {}
        data.setdefault("title", self.id)
        data.setdefault("scope", {})
        data["scope"] = {"decks": list(data["scope"].get("decks") or []), "videos": list(data["scope"].get("videos") or [])}
        data.setdefault("options", {})
        data["id"] = self.id
        return data

    def save_info(self, data: dict) -> dict:
        data = {**data, "id": self.id, "updatedAt": now()}
        write_json(self.path("exam.json"), data)
        return self.info()

    # uploads
    def uploads(self) -> list[dict]:
        folder = self.path("uploads")
        if not folder.is_dir():
            return []
        out = []
        for path in sorted(folder.iterdir()):
            ext = path.suffix.lower().lstrip(".")
            if path.is_symlink() or not path.is_file() or not _NAME.fullmatch(path.name):
                continue
            if ext in IMAGE_TYPES or ext in TEXT_TYPES:
                out.append({
                    "name": path.name, "kind": "image" if ext in IMAGE_TYPES else "text", "size": path.stat().st_size,
                    "url": f"/files/{self.course.id}/{config.EXAMS}/{self.id}/uploads/{path.name}",
                })  # fmt: skip
        return out

    def upload_path(self, name: str) -> Path:
        return self.path("uploads", upload_name(name))

    def save_upload(self, filename: str, data: bytes) -> dict:
        """Store one past paper as uploaded: an image (png/jpg/webp) or UTF-8 text (txt/md)."""
        raw = Path(filename.replace("\\", "/")).name or "upload"
        ext = raw.rsplit(".", 1)[-1].lower() if "." in raw else ""
        ext = {"jpeg": "jpg", "markdown": "md"}.get(ext, ext)
        if ext in IMAGE_TYPES:
            try:
                note_assets.check_image(raw, data, svg=False)
            except note_assets.AssetError as exc:
                raise (UploadTooLarge if len(data) > note_assets.MAX_BYTES else UploadError)(str(exc)) from exc
        elif ext in TEXT_TYPES:
            if not data.strip():
                raise UploadError("文字檔是空的")
            if len(data) > MAX_TEXT_BYTES:
                raise UploadTooLarge("文字檔不能超過 1 MB")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise UploadError("文字檔必須是 UTF-8 編碼") from exc
        else:
            raise UploadError("只能上傳 png、jpg、webp 圖片或 txt、md 文字檔")
        stem = slugify(raw)[:60].strip("-_") or "upload"
        return self._write_upload(stem, ext, data)

    def save_text(self, text: str) -> dict:
        """Pasted text becomes `pasted-<hash>.md`; pasting the same text twice keeps one copy."""
        if not isinstance(text, str) or not text.strip():
            raise UploadError("文字是空的")
        if len(text) > MAX_PASTE_CHARS:
            raise UploadError(f"貼上的文字不能超過 {MAX_PASTE_CHARS:,} 字")
        data = text.encode("utf-8")
        name = f"pasted-{hashlib.sha256(data).hexdigest()[:10]}.md"
        if self.upload_path(name).exists():
            return next(u for u in self.uploads() if u["name"] == name)
        return self._write_upload(name[:-3], "md", data)

    def _write_upload(self, stem: str, ext: str, data: bytes) -> dict:
        with self.locked():
            if len(self.uploads()) >= MAX_UPLOADS:
                raise UploadError(f"每份考試最多 {MAX_UPLOADS} 個上傳檔")
            root = self.path("uploads")
            name, count = f"{stem}.{ext}", 2
            while True:
                try:
                    with exclusive_output(root / name, root=root) as output:
                        output.write(data)
                    break
                except FileExistsError:
                    name, count = f"{stem}-{count}.{ext}", count + 1
        return next(u for u in self.uploads() if u["name"] == name)

    def delete_upload(self, name: str) -> None:
        path = self.upload_path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        unlink_output(path)

    # handout
    def section_path(self, n: int) -> Path:
        return self.path("handout", section_name(n))

    def section_numbers(self) -> list[int]:
        folder = self.path("handout")
        if not folder.is_dir():
            return []
        return sorted(int(m[1]) for p in folder.iterdir() if (m := _SECTION.fullmatch(p.name)) and int(m[1]) >= 1)

    def section(self, n: int) -> tuple[dict, str] | None:
        return notefile.read(self.section_path(n))

    def sections(self) -> list[dict]:
        """Section summaries in reading order: {section, title, status, updatedAt, sources}."""
        out = []
        for n in self.section_numbers():
            found = self.section(n)
            if found is None:
                continue
            meta, _ = found
            out.append({
                "section": n, "title": str(meta.get("title") or f"第 {n} 節"), "status": meta.get("status", "edited"),
                "updatedAt": str(meta["updatedAt"]) if meta.get("updatedAt") else None,
                "sources": [str(s) for s in meta.get("sources") or []],
            })  # fmt: skip
        return out

    def save_section(self, n: int, markdown: str) -> dict:
        """The user's save: marks the section edited, like PUT on a note."""
        path = self.section_path(n)
        with notefile.locked(path):
            current = notefile.read(path)
            meta = current[0] if current else {"section": n, "title": _first_heading(markdown) or f"第 {n} 節"}
            meta.update(status="edited", updatedAt=now())
            write_text(path, notefile.dump(meta, markdown))
        return meta

    # quiz
    def quiz(self) -> dict | None:
        data = read_json(self.path("quiz.json"))
        return data if isinstance(data, dict) and isinstance(data.get("questions"), list) else None

    def save_quiz(self, questions: list[dict]) -> dict:
        quiz = {"version": 1, "generatedAt": now(), "hash": quiz_hash(questions), "questions": questions}
        write_json(self.path("quiz.json"), quiz)
        return quiz

    # attempts
    def attempt_path(self, attempt_id: str) -> Path:
        if not isinstance(attempt_id, str) or not _ATTEMPT.fullmatch(attempt_id):
            raise ValueError("作答紀錄 ID 格式不正確")
        return self.path("attempts", f"{attempt_id}.json")

    def attempt(self, attempt_id: str) -> dict | None:
        data = read_json(self.attempt_path(attempt_id))
        return data if isinstance(data, dict) else None

    def save_attempt(self, attempt: dict) -> None:
        write_json(self.attempt_path(attempt["id"]), attempt)

    def attempts(self) -> list[dict]:
        folder = self.path("attempts")
        if not folder.is_dir():
            return []
        out = []
        for path in folder.glob("*.json"):
            if not _ATTEMPT.fullmatch(path.stem) or path.is_symlink():
                continue
            data = read_json(path)
            if isinstance(data, dict):
                out.append({k: data.get(k) for k in ("id", "submittedAt", "score", "maxScore")})
        return sorted(out, key=lambda a: a.get("submittedAt") or "", reverse=True)

    def summary(self) -> dict:
        info, quiz = self.info(), self.quiz()
        return {
            **{k: info.get(k) for k in ("id", "title", "updatedAt", "scope")},
            "uploadCount": len(self.uploads()), "sectionCount": len(self.section_numbers()),
            "questionCount": len(quiz["questions"]) if quiz else 0,
        }  # fmt: skip


def new_attempt_id() -> str:
    return secrets.token_hex(16)


def quiz_hash(questions: list[dict]) -> str:
    return hashlib.sha256(json.dumps(questions, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _first_heading(markdown: str) -> str:
    m = re.search(r"^#{1,3}\s+(.+?)\s*$", markdown, re.MULTILINE)
    return m[1][:80] if m else ""


def list_exams(course: Course) -> list[Exam]:
    folder = course.path(config.EXAMS)
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.iterdir()):
        try:
            exam = Exam(course, p.name)
        except ValueError:
            continue
        if not p.is_symlink() and exam.exists():
            out.append(exam)
    return out



def save_handout_asset(exam: Exam, filename: str, data: bytes) -> str:
    """An image pasted into the handout editor, under the same rules as note assets; returns `assets/<name>`."""
    return note_assets.save_image(exam.path("handout", "assets"), exam.path("handout"), filename, data)
