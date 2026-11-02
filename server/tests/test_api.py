from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from marginalia import config
from marginalia.api import create_app
from marginalia.jobs import JobRunner
from marginalia.store import Course


def make_course(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path / "courses")
    course = Course("demo")
    course.materials.mkdir(parents=True)
    course.save_info({"title": "測試課"})
    course.save_manifest(
        {
            "decks": [{"id": "week-1", "title": "第一週", "source": "materials/a.pdf"}],
            "videos": [],
        }
    )
    return course


def test_file_path_stays_inside_course(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    assert client.get(f"/files/{course.id}/../../etc/passwd").status_code == 404


def test_video_suffix_range(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    (course.materials / "clip.mp4").write_bytes(b"0123456789")
    client = TestClient(create_app(JobRunner()))
    response = client.get(
        f"/files/{course.id}/materials/clip.mp4", headers={"Range": "bytes=-3"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 7-9/10"
    assert response.content == b"789"


def test_note_write_marks_edited_and_reads_frontmatter(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    response = client.put(
        "/api/courses/demo/decks/week-1/notes/1", json={"markdown": "內容"}
    )
    assert response.status_code == 200
    assert response.json()["meta"]["status"] == "edited"
    response = client.get("/api/courses/demo/decks/week-1/notes/1")
    assert response.json()["markdown"] == "內容"
    assert response.json()["meta"]["slide"] == 1


def test_chat_context_deck_must_belong_to_course(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    response = client.post(
        "/api/agents/chat",
        json={"course": "demo", "message": "測試", "context": {"deck": "../../tmp"}},
    )
    assert response.status_code == 404


def test_job_transitions_to_done(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    runner = JobRunner()

    async def run():
        job = await runner.create(course, "scan")
        await runner.tasks[job["id"]]
        return runner.get(job["id"])

    job = asyncio.run(run())
    assert job["state"] == "done"
    assert job["progress"] == 1.0
