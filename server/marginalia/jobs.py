"""Small persistent job runner for the local server."""

from __future__ import annotations

import asyncio
import importlib
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import align, config, ingest, slides, transcribe
from .course_access import check_course
from .store import Course, list_courses, read_json, write_json

Job = dict[str, Any]
Listener = Callable[[Job], Awaitable[None] | None]
CPU_KINDS = {"render", "align", "transcribe", "pipeline"}


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


class JobRunner:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.listeners: set[Listener] = set()
        self.cpu = asyncio.Lock()
        self.cancel_requested: set[str] = set()

    def _path(self, course: Course, job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("工作 ID 格式不正確")
        return course.path(config.GENERATED, "jobs", f"{job_id}.json")

    def _save(self, job: Job) -> None:
        write_json(self._path(Course(job["course"]), job["id"]), job)

    async def _publish(self, job: Job) -> None:
        self._save(job)
        for listener in list(self.listeners):
            result = listener(job.copy())
            if result is not None:
                await result

    async def recover(self) -> None:
        """Load completed jobs and fail jobs interrupted by a server restart."""
        for course in list_courses():
            try:
                check_course(course)
            except ValueError:
                continue
            for path in (course.gen / "jobs").glob("*.json"):
                job = read_json(path)
                if (
                    not isinstance(job, dict)
                    or not isinstance(job.get("id"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", job["id"])
                    or path.stem != job["id"]
                    or job.get("course") != course.id
                    or not isinstance(job.get("state"), str)
                    or job.get("state")
                    not in {"queued", "running", "done", "failed", "cancelled"}
                ):
                    continue
                if job.get("state") in {"queued", "running"}:
                    job.update(
                        state="failed", error="伺服器重啟，請重跑", finishedAt=_now()
                    )
                    write_json(path, job)
                self.jobs[job["id"]] = job

    def all(self, course_id: str | None = None) -> list[Job]:
        jobs = self.jobs.values()
        if course_id:
            jobs = (j for j in jobs if j["course"] == course_id)
        return sorted(
            (j.copy() for j in jobs), key=lambda j: j["createdAt"], reverse=True
        )

    def get(self, job_id: str) -> Job | None:
        job = self.jobs.get(job_id)
        return job.copy() if job else None

    async def create(self, course: Course, kind: str, **params: Any) -> Job:
        check_course(course)
        if kind not in {
            "pipeline",
            "scan",
            "render",
            "align",
            "transcribe",
            "generate",
            "review",
        }:
            raise ValueError("不支援的工作種類")
        job: Job = {
            "id": uuid.uuid4().hex,
            "course": course.id,
            "kind": kind,
            "state": "queued",
            "progress": 0.0,
            "message": "等待執行",
            "steps": [
                {
                    "name": kind,
                    "state": "queued",
                    "progress": 0.0,
                    "message": "等待執行",
                }
            ],
            "createdAt": _now(),
            "params": params,
        }
        self.jobs[job["id"]] = job
        await self._publish(job)
        self.tasks[job["id"]] = asyncio.create_task(self._run(job["id"]))
        return job.copy()

    async def cancel(self, job_id: str) -> Job | None:
        job = self.jobs.get(job_id)
        if not job or job["state"] in {"done", "failed", "cancelled"}:
            return self.get(job_id)
        if job_id in self.cancel_requested:
            return self.get(job_id)
        self.cancel_requested.add(job_id)
        if job["state"] == "queued":
            job.update(state="cancelled", finishedAt=_now(), message="已取消")
            job["steps"][0].update(state="cancelled", message="已取消")
        else:
            job["message"] = "取消中，等待目前步驟結束"
        await self._publish(job)
        return self.get(job_id)

    def _checkpoint(self, job: Job) -> None:
        if job["id"] in self.cancel_requested:
            raise asyncio.CancelledError

    async def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        loop = asyncio.get_running_loop()

        def progress(fraction: float, message: str) -> None:
            job["progress"] = max(0.0, min(1.0, fraction))
            job["message"] = message
            job["steps"][0].update(progress=job["progress"], message=message)
            loop.call_soon_threadsafe(asyncio.create_task, self._publish(job.copy()))

        try:
            self._checkpoint(job)
            job.update(state="running", startedAt=_now(), message="執行中")
            job["steps"][0].update(state="running", message="執行中")
            await self._publish(job)
            if job["kind"] in CPU_KINDS:
                execution = asyncio.create_task(self._execute_reserved(job, progress))
                try:
                    await asyncio.shield(execution)
                except asyncio.CancelledError:
                    self.cancel_requested.add(job_id)
                    while not execution.done():
                        try:
                            await asyncio.shield(execution)
                        except asyncio.CancelledError:
                            continue
                    # The reservation belongs to execution, even during shutdown.
                    if not execution.cancelled():
                        execution.result()
                    raise
            else:
                await self._execute(job, progress)
            self._checkpoint(job)
            job.update(state="done", progress=1.0, message="完成", finishedAt=_now())
            job["steps"][0].update(state="done", progress=1.0, message="完成")
        except asyncio.CancelledError:
            job.update(state="cancelled", message="已取消", finishedAt=_now())
            job["steps"][0].update(state="cancelled", message="已取消")
        except Exception as exc:  # noqa: BLE001 - job errors must become persisted state
            error = str(exc) if "尚未安裝，請先合入 K2" in str(exc) else "工作執行失敗"
            job.update(
                state="failed", error=error, message="執行失敗", finishedAt=_now()
            )
            job["steps"][0].update(state="failed", message="執行失敗")
        finally:
            await self._publish(job)
            self.tasks.pop(job_id, None)
            self.cancel_requested.discard(job_id)

    async def _execute_reserved(
        self, job: Job, progress: Callable[[float, str], None]
    ) -> None:
        async with self.cpu:
            self._checkpoint(job)
            await self._execute(job, progress)

    async def _execute(self, job: Job, progress: Callable[[float, str], None]) -> None:
        course = Course(job["course"])
        check_course(course)
        self._checkpoint(job)
        params = job["params"]
        kind = job["kind"]
        if kind == "scan":
            await asyncio.to_thread(ingest.scan, course)
        elif kind == "render":
            decks = params.get("decks") or [d["id"] for d in course.manifest()["decks"]]
            for n, deck in enumerate(decks, 1):
                self._checkpoint(job)
                await asyncio.to_thread(
                    slides.render_deck,
                    course,
                    deck,
                    lambda f, m, n=n: progress((n - 1 + f) / len(decks), m),
                )
        elif kind == "align":
            videos = params.get("videos") or [
                v["id"] for v in course.manifest()["videos"]
            ]
            for n, video in enumerate(videos, 1):
                self._checkpoint(job)
                await asyncio.to_thread(
                    align.align_course,
                    course,
                    lambda f, m, n=n: progress((n - 1 + f) / len(videos), m),
                    [video],
                )
        elif kind == "transcribe":
            videos = params.get("videos") or [
                v["id"] for v in course.manifest()["videos"]
            ]
            for n, video in enumerate(videos, 1):
                self._checkpoint(job)
                await asyncio.to_thread(
                    transcribe.transcribe_video,
                    course,
                    video,
                    lambda f, m, n=n: progress((n - 1 + f) / len(videos), m),
                )
        elif kind == "pipeline":
            module = importlib.import_module("marginalia.pipeline")

            def pipeline_progress(fraction: float, message: str) -> None:
                self._checkpoint(job)
                progress(fraction, message)

            await asyncio.to_thread(
                module.process,
                course,
                decks=params.get("decks"),
                progress=pipeline_progress,
            )
        else:
            module_name = (
                "marginalia.notes.generate"
                if kind == "generate"
                else "marginalia.notes.review"
            )
            try:
                fn = (
                    importlib.import_module(module_name).generate_deck
                    if kind == "generate"
                    else importlib.import_module(module_name).review_deck
                )
            except ImportError as exc:
                raise RuntimeError(
                    f"{kind} 模組尚未安裝，請先合入 K2：{exc.name}"
                ) from exc
            decks = params.get("decks") or [d["id"] for d in course.manifest()["decks"]]
            for n, deck in enumerate(decks, 1):
                self._checkpoint(job)
                await asyncio.to_thread(
                    fn,
                    course,
                    deck,
                    progress=lambda f, m, n=n: progress((n - 1 + f) / len(decks), m),
                    **{**params.get("options", {}), "slides": params.get("slides")},
                )


runner = JobRunner()
