"""The local-only HTTP API used by the Marginalia development UI."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import ingest
from .agents import chat
from .jobs import JobRunner, runner
from .llm.accounts import accounts
from .store import (
    Course,
    list_courses,
    read_json,
    slide_name,
    slugify,
    write_json,
    write_text,
)


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status, detail)


def _course(course_id: str) -> Course:
    try:
        course = Course(course_id)
    except ValueError as exc:
        raise _error(404, "找不到課程") from exc
    if not course.exists():
        raise _error(404, "找不到課程")
    return course


def _deck(course: Course, deck: str) -> dict[str, Any]:
    value = course.deck(deck)
    if not value:
        raise _error(404, "找不到簡報")
    return value


def _parse_note(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_text("utf-8")
    except FileNotFoundError:
        raise _error(404, "找不到筆記")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if not match:
        return {}, raw
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise _error(500, "筆記 frontmatter 格式錯誤") from exc
    return meta, match.group(2)


def _note_response(course: Course, deck: str, index: int) -> dict[str, Any] | None:
    path = course.note_path(deck, index)
    if not path.exists():
        return None
    meta, _ = _parse_note(path)
    return {"status": meta.get("status"), "updatedAt": meta.get("updatedAt")}


def _safe_file(course: Course, path: str) -> Path:
    candidate = (course.dir / path).resolve()
    try:
        candidate.relative_to(course.dir.resolve())
    except ValueError as exc:
        raise _error(404, "找不到檔案") from exc
    if not candidate.is_file():
        raise _error(404, "找不到檔案")
    return candidate


def _range_response(path: Path, request: Request):
    size = path.stat().st_size
    value = request.headers.get("range")
    if not value:
        return FileResponse(path, headers={"Accept-Ranges": "bytes"})
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match:
        return JSONResponse(
            {"detail": "不支援的 Range"},
            status_code=416,
            headers={"Content-Range": f"bytes */{size}"},
        )
    start = (
        int(match.group(1))
        if match.group(1)
        else max(0, size - int(match.group(2) or 0))
    )
    end = int(match.group(2)) if match.group(1) and match.group(2) else size - 1
    if start >= size or start > end:
        return JSONResponse(
            {"detail": "不支援的 Range"},
            status_code=416,
            headers={"Content-Range": f"bytes */{size}"},
        )
    end = min(end, size - 1)

    def body():
        with path.open("rb") as file:
            file.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = file.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        body(),
        status_code=206,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        },
    )


class CourseCreate(BaseModel):
    title: str = Field(min_length=1)
    id: str | None = None


class NoteUpdate(BaseModel):
    markdown: str


class SegmentUpdate(BaseModel):
    video: str
    start: float
    end: float
    deck: str | None = None
    slide: int | None = None


class JobRequest(BaseModel):
    kind: str
    decks: list[str] | None = None
    videos: list[str] | None = None
    slides: list[int] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await app.state.jobs.recover()
    yield


def create_app(job_runner: JobRunner = runner) -> FastAPI:
    app = FastAPI(title="Marginalia local API", lifespan=_lifespan)
    app.state.jobs = job_runner

    @app.get("/api/health")
    async def health():
        return {"mode": "local", "version": "0.1.0"}

    @app.get("/api/courses")
    async def courses():
        result = []
        for course in list_courses():
            manifest = course.manifest()
            result.append(
                {
                    "id": course.id,
                    "title": course.info()["title"],
                    "subtitle": course.info().get("subtitle", ""),
                    "deckCount": len(manifest["decks"]),
                    "videoCount": len(manifest["videos"]),
                    "updatedAt": course.info().get("updatedAt"),
                }
            )
        return result

    @app.post("/api/courses")
    async def create_course(body: CourseCreate):
        course_id = body.id or slugify(body.title)
        try:
            course = Course(course_id)
        except ValueError as exc:
            raise _error(422, "課程 ID 格式不正確") from exc
        if course.exists():
            raise _error(409, "課程已存在")
        course.materials.mkdir(parents=True)
        course.save_info(
            {
                "title": body.title,
                "language": "en+zh-TW",
                "videoUrls": {},
                "hiddenDecks": [],
            }
        )
        course.save_manifest({"decks": [], "videos": []})
        return course.info()

    @app.get("/api/courses/{course_id}")
    async def course_detail(course_id: str):
        course = _course(course_id)
        manifest = course.manifest()
        return {
            "info": course.info(),
            "decks": manifest["decks"],
            "videos": manifest["videos"],
            "status": course.status(),
        }

    @app.put("/api/courses/{course_id}")
    async def update_course(course_id: str, body: dict[str, Any]):
        course = _course(course_id)
        allowed = {"title", "subtitle", "language", "videoUrls", "hiddenDecks"}
        info = course.info()
        info.update({key: value for key, value in body.items() if key in allowed})
        info["updatedAt"] = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
        course.save_info(info)
        return course.info()

    @app.post("/api/courses/{course_id}/upload")
    async def upload(
        course_id: str,
        files: Annotated[list[UploadFile], File()],
        folder: str | None = None,
    ):
        course = _course(course_id)
        parts = Path(folder or "").parts
        if (
            any(part in {"", ".", ".."} for part in parts)
            or Path(folder or "").is_absolute()
        ):
            raise _error(422, "資料夾路徑不正確")
        target = course.materials.joinpath(*parts)
        target.mkdir(parents=True, exist_ok=True)
        saved = []
        for upload_file in files:
            raw_name = Path(upload_file.filename or "upload").name
            name = slugify(Path(raw_name).stem) + Path(raw_name).suffix.lower()
            if name in {"", ".", ".."}:
                raise _error(422, "檔名不正確")
            destination = target / name
            stem, suffix, count = destination.stem, destination.suffix, 2
            while destination.exists():
                destination = target / f"{stem}-{count}{suffix}"
                count += 1
            with destination.open("wb") as output:
                while chunk := await upload_file.read(1024 * 1024):
                    output.write(chunk)
            saved.append(str(destination.relative_to(course.dir)))
        return {
            "saved": saved,
            "manifest": await asyncio.to_thread(ingest.scan, course),
        }

    @app.post("/api/courses/{course_id}/scan")
    async def scan(course_id: str):
        return await asyncio.to_thread(ingest.scan, _course(course_id))

    @app.get("/api/courses/{course_id}/decks/{deck}")
    async def deck_detail(course_id: str, deck: str):
        course = _course(course_id)
        deck_info = _deck(course, deck)
        values = []
        from .align import slide_ranges

        for slide in course.slides(deck):
            index = slide.get("index")
            values.append(
                {
                    **slide,
                    "image": f"/files/{course.id}/generated/decks/{deck}/slides/{slide_name(index)}.webp",
                    "thumb": f"/files/{course.id}/generated/decks/{deck}/thumbs/{slide_name(index)}.webp",
                    "ranges": slide_ranges(course, deck, index),
                    "note": _note_response(course, deck, index),
                }
            )
        return {"deck": deck_info, "slides": values}

    @app.get("/api/courses/{course_id}/decks/{deck}/notes/{index}")
    async def get_note(course_id: str, deck: str, index: int):
        course = _course(course_id)
        _deck(course, deck)
        meta, markdown = _parse_note(course.note_path(deck, index))
        return {
            "markdown": markdown,
            "meta": meta,
            "review": read_json(course.review_path(deck, index)),
        }

    @app.put("/api/courses/{course_id}/decks/{deck}/notes/{index}")
    async def put_note(course_id: str, deck: str, index: int, body: NoteUpdate):
        course = _course(course_id)
        _deck(course, deck)
        path = course.note_path(deck, index)
        meta, _ = _parse_note(path) if path.exists() else ({"slide": index}, "")
        meta.update(
            status="edited",
            updatedAt=datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        )
        write_text(
            path,
            "---\n"
            + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
            + "\n---\n\n"
            + body.markdown,
        )
        return {"meta": meta}

    @app.get("/api/courses/{course_id}/videos/{video}/transcript")
    async def transcript(
        course_id: str,
        video: str,
        from_: float | None = Query(None, alias="from"),
        to: float | None = None,
    ):
        course = _course(course_id)
        if not course.video(video):
            raise _error(404, "找不到影片")
        complete = course.transcript(video)
        partial = complete is None
        data = complete or read_json(
            course.video_dir(video) / "transcript.partial.json", {"segments": []}
        )
        segments = data.get("segments", [])
        if from_ is not None:
            segments = [segment for segment in segments if segment["end"] >= from_]
        if to is not None:
            segments = [segment for segment in segments if segment["start"] <= to]
        return {"segments": segments, "partial": partial}

    @app.get("/api/courses/{course_id}/alignment")
    async def alignment(course_id: str):
        return _course(course_id).alignment()

    @app.put("/api/courses/{course_id}/alignment/segments")
    async def update_segment(course_id: str, body: SegmentUpdate):
        course = _course(course_id)
        if body.start < 0 or body.end <= body.start or not course.video(body.video):
            raise _error(422, "對齊片段不正確")
        if body.deck and not course.deck(body.deck):
            raise _error(422, "找不到簡報")
        data = course.alignment()
        data.setdefault("segments", []).append({**body.model_dump(), "manual": True})
        data["segments"].sort(key=lambda value: (value["video"], value["start"]))
        write_json(course.gen / "alignment.json", data)
        return data

    @app.get("/files/{course_id}/{path:path}")
    async def files(course_id: str, path: str, request: Request):
        course = _course(course_id)
        file = _safe_file(course, path)
        return (
            _range_response(file, request)
            if file.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
            else FileResponse(file)
        )

    @app.post("/api/courses/{course_id}/jobs")
    async def create_job(course_id: str, body: JobRequest):
        course = _course(course_id)
        job = await app.state.jobs.create(
            course,
            body.kind,
            decks=body.decks,
            videos=body.videos,
            slides=body.slides,
            options=body.options,
        )
        return {"id": job["id"]}

    @app.get("/api/jobs")
    async def jobs(course: str | None = None):
        return app.state.jobs.all(course)

    @app.get("/api/jobs/{job_id}")
    async def job(job_id: str):
        result = app.state.jobs.get(job_id)
        if not result:
            raise _error(404, "找不到工作")
        return result

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        result = await app.state.jobs.cancel(job_id)
        if not result:
            raise _error(404, "找不到工作")
        return result

    @app.get("/api/events")
    async def events(request: Request):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def listener(job: dict[str, Any]) -> None:
            await queue.put(job)

        async def body():
            app.state.jobs.listeners.add(listener)
            try:
                while not await request.is_disconnected():
                    try:
                        job = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"event: job\ndata: {json.dumps(job, ensure_ascii=False)}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                app.state.jobs.listeners.discard(listener)

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/agents/accounts")
    async def agent_accounts():
        return accounts()

    @app.post("/api/agents/chat")
    async def agent_chat(body: dict[str, Any]):
        for key in ("course", "message"):
            if not isinstance(body.get(key), str) or not body[key].strip():
                raise _error(422, "聊天請求不完整")
        course = _course(body["course"])
        context = body.get("context") or {}
        if not isinstance(context, dict):
            raise _error(422, "聊天情境格式不正確")
        deck = context.get("deck")
        if deck is not None:
            if not isinstance(deck, str):
                raise _error(422, "簡報情境格式不正確")
            _deck(course, deck)
        slide = context.get("slide")
        if slide is not None and (not isinstance(slide, int) or slide < 1):
            raise _error(422, "投影片情境格式不正確")
        region = context.get("region")
        if region is not None:
            try:
                coordinates = [float(region[key]) for key in ("x", "y", "w", "h")]
            except (KeyError, TypeError, ValueError):
                raise _error(422, "圈選範圍格式不正確") from None
            x, y, width, height = coordinates
            if (
                min(coordinates) < 0
                or width <= 0
                or height <= 0
                or x + width > 1
                or y + height > 1
            ):
                raise _error(422, "圈選範圍格式不正確")
        account_id = body.get("account", "claude")
        account = next((item for item in accounts() if item["id"] == account_id), None)
        if not account or not account.get("loggedIn"):
            raise _error(422, "指定的模型帳號未登入")
        if body.get("model") and body["model"] not in {
            model["id"] for model in account["models"]
        }:
            raise _error(422, "指定的模型不可用")
        if body.get("effort") and body["effort"] not in account["efforts"]:
            raise _error(422, "指定的推理強度不可用")

        async def body_events():
            try:
                async for event in chat.stream(body):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:  # noqa: BLE001 - turn local CLI errors into an SSE event
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            body_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/courses/{course_id}/chats")
    async def chats(course_id: str):
        course = _course(course_id)
        result = []
        for path in course.chats_dir.glob("*.json"):
            data = read_json(path, {})
            if data:
                result.append(
                    {key: data.get(key) for key in ("id", "title", "mode", "updatedAt")}
                )
        return sorted(
            result, key=lambda item: item.get("updatedAt") or "", reverse=True
        )

    @app.get("/api/courses/{course_id}/chats/{chat_id}")
    async def get_chat(course_id: str, chat_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", chat_id):
            raise _error(404, "找不到對話")
        data = read_json(_course(course_id).chats_dir / f"{chat_id}.json")
        if not data:
            raise _error(404, "找不到對話")
        return data

    return app


app = create_app()
