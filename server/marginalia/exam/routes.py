"""HTTP routes for exam prep (table in docs/architecture.md, Exam prep → HTTP API)."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import note_assets
from ..llm.accounts import accounts
from ..store import Course, slugify, validate_id
from . import grade
from .context import Engine
from .schema import SUBJECTIVE, TYPES
from .store import (
    Exam,
    UploadError,
    UploadTooLarge,
    list_exams,
    new_attempt_id,
    now,
    save_handout_asset,
)

MAX_REQUEST = 40 * 1024 * 1024  # one multipart upload request; enforced by Content-Length in api.py


class ExamCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    id: str | None = None
    scope: dict[str, Any] | None = None
    options: dict[str, Any] | None = None


class ExamUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    scope: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    hidden: bool | None = None


class PastedText(BaseModel):
    text: str


class SectionUpdate(BaseModel):
    markdown: str = Field(max_length=200_000)


class AttemptCreate(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    startedAt: str | None = None
    durationSec: float | None = None


class GradeRequest(BaseModel):
    question: str
    answer: str | None = Field(None, max_length=grade.MAX_ANSWER)
    account: str = "claude"
    model: str | None = None
    effort: str | None = None


def _error(status: int, detail: str) -> HTTPException:
    return HTTPException(status, detail)


async def engine_for(account_id: str, model: str | None, effort: str | None) -> Engine:
    """An Engine on a logged-in subscription account, validated like chat requests."""
    account = next((a for a in await asyncio.to_thread(accounts) if a["id"] == account_id), None)
    if not account or not account.get("loggedIn"):
        raise _error(422, "指定的模型帳號未登入")
    if model and model not in {m["id"] for m in account["models"]}:
        raise _error(422, "指定的模型不可用")
    if effort and effort not in account["efforts"]:
        raise _error(422, "指定的推理強度不可用")
    return Engine(account_id, model, effort)


def _scope(course: Course, value: Any) -> dict:
    if value is None:
        return {"decks": [], "videos": []}
    if not isinstance(value, dict):
        raise _error(422, "考試範圍格式不正確")
    manifest = course.manifest()
    hidden = set(course.info().get("hiddenDecks") or [])
    decks = {d["id"] for d in manifest["decks"] if d["id"] not in hidden and not d.get("hidden")}
    known = {"decks": decks, "videos": {v["id"] for v in manifest["videos"]}}
    out = {}
    for key in ("decks", "videos"):
        items = value.get(key) or []
        if not isinstance(items, list) or not all(isinstance(i, str) and i in known[key] for i in items):
            raise _error(422, "考試範圍包含不存在的簡報或影片")
        out[key] = list(dict.fromkeys(items))
    return out


def _options(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _error(422, "考試設定格式不正確")
    out: dict[str, Any] = {}
    for key, limit in (("questionCount", 100), ("minutes", 600)):
        if value.get(key) is not None:
            if not isinstance(value[key], int) or not 1 <= value[key] <= limit:
                raise _error(422, "考試設定格式不正確")
            out[key] = value[key]
    if value.get("types") is not None:
        if not isinstance(value["types"], list) or not value["types"] or set(value["types"]) - set(TYPES):
            raise _error(422, "題型設定不正確")
        out["types"] = [t for t in TYPES if t in value["types"]]
    return out


_grading_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def router(course_of: Callable[[str], Course]) -> APIRouter:
    api = APIRouter(prefix="/api/courses/{course_id}/exams")

    def exam_of(course_id: str, exam_id: str) -> Exam:
        course = course_of(course_id)
        try:
            exam = Exam(course, exam_id)
        except ValueError as exc:
            raise _error(404, "找不到考試") from exc
        if not exam.exists():
            raise _error(404, "找不到考試")
        return exam

    def detail(exam: Exam) -> dict:
        quiz = exam.quiz()
        return {
            "exam": exam.info(), "uploads": exam.uploads(), "handout": exam.sections(),
            "quiz": {k: quiz.get(k) for k in ("hash", "generatedAt")} | {"questionCount": len(quiz["questions"])}
            if quiz else None,
        }  # fmt: skip

    @api.get("")
    async def exams(course_id: str):
        return [exam.summary() for exam in list_exams(course_of(course_id))]

    @api.post("")
    async def create_exam(course_id: str, body: ExamCreate):
        course = course_of(course_id)
        try:
            exam = Exam(course, validate_id(body.id or slugify(body.title)))
        except ValueError as exc:
            raise _error(422, "考試 ID 格式不正確") from exc
        scope, options = _scope(course, body.scope), _options(body.options)
        with exam.locked():
            if exam.exists():
                raise _error(409, "考試已存在")
            return exam.save_info({"title": body.title.strip(), "createdAt": now(), "scope": scope,
                                   "options": options, "hidden": False})  # fmt: skip

    @api.get("/{exam_id}")
    async def get_exam(course_id: str, exam_id: str):
        return detail(exam_of(course_id, exam_id))

    @api.put("/{exam_id}")
    async def update_exam(course_id: str, exam_id: str, body: ExamUpdate):
        exam = exam_of(course_id, exam_id)
        with exam.locked():
            return exam.save_info(_updated(exam, body))

    def _updated(exam: Exam, body: ExamUpdate) -> dict:
        info = exam.info()
        if body.title is not None:
            info["title"] = body.title.strip()
        if body.scope is not None:
            info["scope"] = _scope(exam.course, body.scope)
        if body.options is not None:
            info["options"] = _options(body.options)
        if body.hidden is not None:
            info["hidden"] = body.hidden
        return info

    @api.post("/{exam_id}/uploads")
    async def upload(course_id: str, exam_id: str, files: Annotated[list[UploadFile], File()]):
        exam = exam_of(course_id, exam_id)
        for item in files:
            data = await item.read(note_assets.MAX_BYTES + 1)
            try:
                await asyncio.to_thread(exam.save_upload, item.filename or "upload", data)
            except UploadError as exc:
                raise _error(413 if isinstance(exc, UploadTooLarge) else 422, f"{item.filename}：{exc}") from exc
            except (ValueError, OSError) as exc:
                raise _error(422, "檔案路徑不正確") from exc
        return {"uploads": exam.uploads()}

    @api.post("/{exam_id}/uploads/text")
    async def upload_text(course_id: str, exam_id: str, body: PastedText):
        exam = exam_of(course_id, exam_id)
        try:
            return await asyncio.to_thread(exam.save_text, body.text)
        except UploadError as exc:
            raise _error(422, str(exc)) from exc

    @api.delete("/{exam_id}/uploads/{name}")
    async def delete_upload(course_id: str, exam_id: str, name: str):
        exam = exam_of(course_id, exam_id)
        try:
            exam.delete_upload(name)
        except (ValueError, FileNotFoundError) as exc:
            raise _error(404, "找不到上傳檔") from exc
        return {"uploads": exam.uploads()}

    def section_index(n: int) -> int:
        if not 1 <= n <= 999:
            raise _error(422, "講義段落編號不正確")
        return n

    @api.get("/{exam_id}/handout/{n}")
    async def get_section(course_id: str, exam_id: str, n: int):
        found = exam_of(course_id, exam_id).section(section_index(n))
        if found is None:
            raise _error(404, "找不到講義段落")
        meta, body = found
        return {"markdown": body, "meta": meta}

    @api.put("/{exam_id}/handout/{n}")
    async def put_section(course_id: str, exam_id: str, n: int, body: SectionUpdate):
        exam = exam_of(course_id, exam_id)
        numbers = exam.section_numbers()
        if section_index(n) not in numbers and n != (max(numbers, default=0) + 1):
            raise _error(404, "找不到講義段落")
        return {"meta": await asyncio.to_thread(exam.save_section, n, body.markdown)}

    @api.post("/{exam_id}/assets")
    async def upload_asset(course_id: str, exam_id: str, file: Annotated[UploadFile, File()]):
        exam = exam_of(course_id, exam_id)
        data = await file.read(note_assets.MAX_BYTES + 1)
        try:
            return {"path": await asyncio.to_thread(save_handout_asset, exam, file.filename or "image", data)}
        except note_assets.AssetError as exc:
            raise _error(422, str(exc)) from exc
        except ValueError as exc:
            raise _error(422, "圖片路徑不正確") from exc

    @api.get("/{exam_id}/quiz")
    async def get_quiz(course_id: str, exam_id: str):
        quiz = exam_of(course_id, exam_id).quiz()
        if quiz is None:
            raise _error(404, "還沒有產生題目")
        return quiz

    @api.get("/{exam_id}/attempts")
    async def attempts(course_id: str, exam_id: str):
        return exam_of(course_id, exam_id).attempts()

    @api.post("/{exam_id}/attempts")
    async def submit(course_id: str, exam_id: str, body: AttemptCreate):
        exam = exam_of(course_id, exam_id)
        quiz = exam.quiz()
        if quiz is None:
            raise _error(404, "還沒有產生題目")
        attempt = grade.new_attempt(quiz, body.answers, new_attempt_id(), body.startedAt, body.durationSec)
        await asyncio.to_thread(exam.save_attempt, attempt)
        return attempt

    def attempt_of(exam: Exam, attempt_id: str) -> dict:
        try:
            attempt = exam.attempt(attempt_id)
        except ValueError as exc:
            raise _error(404, "找不到作答紀錄") from exc
        if attempt is None:
            raise _error(404, "找不到作答紀錄")
        return attempt

    @api.get("/{exam_id}/attempts/{attempt_id}")
    async def get_attempt(course_id: str, exam_id: str, attempt_id: str):
        return attempt_of(exam_of(course_id, exam_id), attempt_id)

    @api.post("/{exam_id}/attempts/{attempt_id}/grade")
    async def grade_answer(course_id: str, exam_id: str, attempt_id: str, body: GradeRequest):
        exam = exam_of(course_id, exam_id)
        attempt = attempt_of(exam, attempt_id)
        # Grade against the questions this attempt answered: the quiz may have been regenerated since.
        questions = attempt.get("questions") if isinstance(attempt.get("questions"), list) else None
        if questions is None:
            quiz = exam.quiz() or {}
            if attempt.get("quizHash") != quiz.get("hash"):
                raise _error(409, "題目已重新產生，這份作答紀錄不能再批改")
            questions = quiz.get("questions", [])
        question = next((q for q in questions if isinstance(q, dict) and q.get("id") == body.question), None)
        if question is None:
            raise _error(404, "找不到題目")
        if question.get("type") not in SUBJECTIVE:
            raise _error(422, "只有簡答、問答、計算題可以請 Agent 批改")
        engine = await engine_for(body.account, body.model, body.effort)
        key = f"{exam.dir}/{attempt_id}"
        lock = _grading_locks.setdefault(key, asyncio.Lock())
        async with lock:
            attempt = attempt_of(exam, attempt_id)
            answer = body.answer if body.answer is not None else attempt["answers"].get(question["id"], "")
            if not isinstance(answer, str) or not answer.strip():
                raise _error(422, "答案是空的")
            try:
                grading = await asyncio.wait_for(grade.agent_grade(question, answer, engine), 300)
            except TimeoutError as exc:
                raise _error(504, "批改逾時，請再試一次") from exc
            except Exception as exc:
                raise _error(502, "Agent 批改失敗，請確認本機登入後重試") from exc
            attempt = attempt_of(exam, attempt_id)  # re-read: only this lock writes gradings
            grade.apply_grading(attempt, question, grading)
            await asyncio.to_thread(exam.save_attempt, attempt)
        return {"grading": grading, "attempt": attempt}

    return api

