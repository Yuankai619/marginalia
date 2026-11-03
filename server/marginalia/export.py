"""Publish an allowlisted, read-only snapshot; never copy raw course directories."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from . import config, note_assets
from .exam.schema import clean_question
from .notes import notefile
from .notes.video_links import has_video_links
from .store import (
    Course,
    _directory_fd,
    atomic_output,
    list_courses,
    slide_name,
    validate_id,
)


def _pick(data: dict, keys: str) -> dict:
    return {key: data[key] for key in keys.split() if key in data}


def _public_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme != "https" or not host or url.username or url.password:
            return False
        _ = url.port  # Reject malformed ports before publishing a URL.
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            pass
        try:
            # Browsers also accept shorthand, octal and hexadecimal IPv4 addresses.
            return ipaddress.ip_address(socket.inet_aton(host)).is_global
        except OSError:
            pass
        return bool(
            re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
            and not host.rsplit(".", 1)[-1].isdigit()
            and not host.endswith(
                (".localhost", ".local", ".internal", ".ts.net", ".lan", ".home.arpa")
            )
        )
    except (TypeError, ValueError):
        return False


def _write(out: Path, relative: str, data: dict | list | bytes) -> None:
    payload = (
        data
        if isinstance(data, bytes)
        else json.dumps(data, ensure_ascii=False, indent=2).encode()
    )
    with atomic_output(out / relative, root=out) as output:
        output.write(payload)
        os.fchmod(output.fileno(), 0o644)


def _read(course: Course, *parts: str) -> bytes | None:
    # Pin the input parents too: a symlink must never turn a published image into a private file.
    path = config.COURSES_DIR.absolute().joinpath(course.id, *parts)
    try:
        with _directory_fd(path.parent, create=False) as directory:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, "rb") as source:
                return source.read()
    except FileNotFoundError:
        return None


def _json(course: Course, *parts: str, default=None):
    data = _read(course, *parts)
    return json.loads(data) if data is not None else default


def _note(course: Course, deck: str, index: int) -> dict | None:
    raw = _read(course, config.NOTES, deck, f"{slide_name(index)}.md")
    if raw is None:
        return None
    text = raw.decode("utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    meta, body = (yaml.safe_load(match[1]) or {}, match[2]) if match else ({}, text)
    if not isinstance(meta, dict):
        raise TypeError("筆記 frontmatter 必須是物件")
    status = meta.get("status", "edited")
    if meta.get("partial") or status not in {
        "generated",
        "reviewed",
        "edited",
        "skipped",
    }:
        return None
    if meta.get("untaught") and status != "edited" and has_video_links(body):
        return None
    public_meta = {"status": status}
    if meta.get("updatedAt"):
        public_meta["updatedAt"] = str(meta["updatedAt"])
    return {"markdown": body, "meta": public_meta}


def _assets(course: Course, deck: str, notes: dict, out: Path) -> None:
    body = unquote("\n".join(note["markdown"] for note in notes.values()))
    names = set(
        re.findall(r"assets/([\w][\w.-]*\.(?:png|jpe?g|webp|svg))", body, re.IGNORECASE)
    )
    for name in sorted(names):
        if ".." in name:
            raise ValueError("圖片路徑不正確")
        data = _read(course, config.NOTES, deck, "assets", name)
        if data is None:
            continue
        if len(data) > note_assets.MAX_BYTES:
            raise ValueError("圖片不能超過 10 MB")
        note_assets._check_content(note_assets._extension(name), data)
        _write(out, f"files/{course.id}/notes/{deck}/assets/{name}", data)


def _exam_assets(course: Course, exam_id: str, markdown: str, out: Path) -> None:
    names = set(re.findall(r"assets/([\w][\w.-]*\.(?:png|jpe?g|webp|svg))", unquote(markdown), re.IGNORECASE))
    for name in sorted(names):
        if ".." in name:
            raise ValueError("圖片路徑不正確")
        data = _read(course, config.EXAMS, exam_id, "handout", "assets", name)
        if data is None:
            continue
        if len(data) > note_assets.MAX_BYTES:
            raise ValueError("圖片不能超過 10 MB")
        note_assets._check_content(note_assets._extension(name), data)
        _write(out, f"files/{course.id}/exams/{exam_id}/handout/assets/{name}", data)


def _section(course: Course, exam_id: str, name: str) -> dict | None:
    raw = _read(course, config.EXAMS, exam_id, "handout", name)
    if raw is None:
        return None
    meta, body = notefile.parse(raw.decode("utf-8"))
    status = meta.get("status", "edited")
    if status not in {"generated", "reviewed", "edited"}:
        return None
    public = {"status": status}
    if meta.get("updatedAt"):
        public["updatedAt"] = str(meta["updatedAt"])
    return {"section": int(name[:3]), "title": str(meta.get("title") or f"第 {int(name[:3])} 節"),
            "markdown": body, "meta": public}  # fmt: skip


def _export_exams(course: Course, out: Path, deck_ids: set[str]) -> None:
    """Handouts and quizzes only: no uploads, attempts, generator scratch or options (architecture.md, Exam prep)."""
    folder = config.COURSES_DIR.absolute() / course.id / config.EXAMS
    summaries = []
    for path in sorted(folder.iterdir()) if folder.is_dir() and not folder.is_symlink() else []:
        try:
            exam_id = validate_id(path.name)
        except ValueError:
            continue
        if path.is_symlink():
            continue
        info = _json(course, config.EXAMS, exam_id, "exam.json")
        if not isinstance(info, dict) or info.get("hidden"):
            continue
        handout_dir = path / "handout"
        names = sorted(
            p.name for p in (handout_dir.iterdir() if handout_dir.is_dir() and not handout_dir.is_symlink() else [])
            if re.fullmatch(r"\d{3}\.md", p.name) and p.name != "000.md"
        )  # fmt: skip
        sections = [s for s in (_section(course, exam_id, n) for n in names) if s]
        for section in sections:
            _exam_assets(course, exam_id, section["markdown"], out)
        quiz = _json(course, config.EXAMS, exam_id, "quiz.json")
        public_quiz = None
        if isinstance(quiz, dict) and isinstance(quiz.get("questions"), list):
            questions = [q for q in (clean_question(q) for q in quiz["questions"]) if q and q["id"]]
            for q in questions:
                q.pop("pastRef", None)
            public_quiz = {"hash": quiz.get("hash"), "questions": questions}
        scope = info.get("scope") or {}
        exam = {"id": exam_id, "title": str(info.get("title") or exam_id),
                "scope": {"decks": [d for d in scope.get("decks") or [] if d in deck_ids]}}  # fmt: skip
        _write(out, f"data/{course.id}/exams/{exam_id}.json", {"exam": exam, "handout": sections, "quiz": public_quiz})
        summaries.append({**exam, "updatedAt": info.get("updatedAt"), "sectionCount": len(sections),
                          "questionCount": len(public_quiz["questions"]) if public_quiz else 0})  # fmt: skip
    _write(out, f"data/{course.id}/exams.json", [{k: v for k, v in s.items() if k != "scope"} for s in summaries])


def _export_course(course: Course, out: Path, only_decks: list[str] | None) -> dict:
    if not course.exists():
        raise ValueError("找不到課程")
    info = _json(course, "course.json", default={})
    info = {"title": course.id.replace("-", " ").title(), **info, "id": course.id}
    manifest = _json(
        course, config.GENERATED, "manifest.json", default={"decks": [], "videos": []}
    )
    for entry in manifest["decks"] + manifest["videos"]:
        validate_id(entry["id"])
    hidden = set(info.get("hiddenDecks", []))
    decks = [
        d
        for d in manifest["decks"]
        if d["id"] not in hidden
        and not d.get("hidden")
        and (only_decks is None or d["id"] in only_decks)
    ]
    videos = manifest["videos"]
    deck_ids, video_ids = {d["id"] for d in decks}, {v["id"] for v in videos}
    public_info = _pick(info, "id title subtitle language updatedAt")
    public_info["videoUrls"] = {
        v: url
        for v, url in info.get("videoUrls", {}).items()
        if v in video_ids and _public_url(url)
    }
    public_decks = []
    segments = []
    for segment in _json(course, config.GENERATED, "alignment.json", default={}).get(
        "segments", []
    ):
        if segment.get("video") not in video_ids or segment.get("deck") not in deck_ids:
            continue
        slide_name(segment.get("slide"))
        segments.append(_pick(segment, "video start end deck slide score manual"))
    for deck in decks:
        deck_id = validate_id(deck["id"])
        public_deck = _pick(deck, "id title date width height")
        notes, slides = {}, []
        for slide in _json(
            course, config.GENERATED, "decks", deck_id, "slides.json", default=[]
        ):
            index = slide["index"]
            name = slide_name(index)
            note = _note(course, deck_id, index)
            if note:
                notes[str(index)] = note
            value = {
                **_pick(slide, "index title text speakerNotes"),
                "note": note["meta"] if note else None,
                "ranges": [
                    _pick(s, "video start end")
                    for s in segments
                    if s["deck"] == deck_id and s["slide"] == index
                ],
            }
            for folder, key in (("slides", "image"), ("thumbs", "thumb")):
                image = _read(
                    course, config.GENERATED, "decks", deck_id, folder, f"{name}.webp"
                )
                if image is not None:
                    relative = f"files/{course.id}/generated/decks/{deck_id}/{folder}/{name}.webp"
                    _write(out, relative, image)
                    value[key] = f"/{relative}"
            slides.append(value)
        public_deck.update(
            slideCount=len(slides), rendered=bool(slides and slides[0].get("image"))
        )
        public_decks.append(public_deck)
        _assets(course, deck_id, notes, out)
        _write(
            out,
            f"data/{course.id}/decks/{deck_id}.json",
            {"deck": public_deck, "slides": slides, "notes": notes},
        )
    public_videos = []
    for video in videos:
        video_id = validate_id(video["id"])
        transcript = _json(
            course, config.GENERATED, "videos", video_id, "transcript.json", default={}
        )
        complete = bool(transcript) and not transcript.get("partial")
        public_videos.append(
            {
                **_pick(video, "id title duration date"),
                "transcriptStatus": "done" if complete else "pending",
            }
        )
        _write(
            out,
            f"data/{course.id}/transcripts/{video_id}.json",
            {
                "segments": [
                    _pick(s, "start end text") for s in transcript.get("segments", [])
                ]
                if complete
                else [],
                "partial": False,
            },
        )
    _write(
        out, f"data/{course.id}/alignment.json", {"videos": {}, "segments": segments}
    )
    _export_exams(course, out, deck_ids)
    _write(
        out,
        f"data/{course.id}/course.json",
        {"info": public_info, "decks": public_decks, "videos": public_videos},
    )
    return {
        **_pick(public_info, "id title subtitle updatedAt"),
        "deckCount": len(decks),
        "videoCount": len(videos),
    }


def export_courses(
    out: Path, courses: list[str] | None = None, decks: list[str] | None = None
) -> int:
    """Export to a fresh data/files namespace so old or hidden content cannot survive a rebuild."""
    out = out.absolute()
    source = config.COURSES_DIR.resolve()
    destination = out.resolve()
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("匯出目錄不能與課程來源重疊")
    if (
        (out / "data").exists()
        or (out / "files").exists()
        or (out / "data").is_symlink()
        or (out / "files").is_symlink()
    ):
        raise ValueError(
            "輸出目錄已有 data 或 files，請指定新的輸出目錄或重新執行 pnpm build"
        )
    for deck in decks or []:
        validate_id(deck)
    selected = (
        [Course(c) for c in dict.fromkeys(courses)] if courses else list_courses()
    )
    summaries = [_export_course(course, out, decks) for course in selected]
    _write(out, "data/courses.json", summaries)
    return len(summaries)
