from __future__ import annotations

import asyncio
import threading

from marginalia import config, slides
from marginalia.jobs import JobRunner
from marginalia.store import Course, read_json


def test_repeated_cancel_keeps_cpu_until_worker_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    course.materials.mkdir(parents=True)
    course.save_manifest({"decks": [{"id": "one"}, {"id": "two"}], "videos": []})
    entered, release = threading.Event(), threading.Event()
    calls = []

    def render(course, deck, progress):
        calls.append(deck)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(slides, "render_deck", render)

    async def run():
        runner = JobRunner()
        first = await runner.create(course, "render")
        first_task = runner.tasks[first["id"]]
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await runner.cancel(first["id"])
            await runner.cancel(first["id"])
            second = await runner.create(course, "render", decks=["three"])
            second_task = runner.tasks[second["id"]]
            await asyncio.sleep(0.03)
            assert calls == ["one"]
            assert runner.cpu.locked()
            release.set()
            await asyncio.gather(first_task, second_task)
            assert calls == ["one", "three"]  # Cancel skips the next deck.
            assert runner.get(first["id"])["state"] == "cancelled"
            assert runner.get(second["id"])["state"] == "done"
        finally:
            release.set()

    asyncio.run(run())


def test_cancel_before_task_starts_is_persisted_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    course.materials.mkdir(parents=True)

    async def run():
        runner = JobRunner()
        job = await runner.create(course, "scan")
        task = runner.tasks[job["id"]]
        result = await runner.cancel(job["id"])
        assert result["state"] == "cancelled" and result["finishedAt"]
        await task
        assert job["id"] not in runner.tasks
        assert (
            read_json(course.gen / "jobs" / f"{job['id']}.json")["state"] == "cancelled"
        )

    asyncio.run(run())


def test_recover_rejects_untrusted_job_identity_and_state(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(config, "COURSES_DIR", tmp_path / "courses")
    course = Course("demo")
    course.materials.mkdir(parents=True)
    root = course.gen / "jobs"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    fixtures = [
        {"id": str(outside), "course": "demo", "state": "paused"},
        {"id": "a" * 32, "course": "other", "state": "running"},
        {"id": "b" * 32, "course": "demo", "state": "paused"},
        {"id": "c" * 32, "course": "demo", "state": []},
    ]
    for n, job in enumerate(fixtures):
        (root / f"{n}.json").write_text(json.dumps(job))
    valid = {"id": "d" * 32, "course": "demo", "state": "running"}
    (root / f"{valid['id']}.json").write_text(json.dumps(valid))

    async def run():
        runner = JobRunner()
        await runner.recover()
        assert list(runner.jobs) == [valid["id"]]
        assert runner.get(valid["id"])["state"] == "failed"
        assert not (outside.with_suffix(".json")).exists()

    asyncio.run(run())


def test_note_jobs_forward_requested_slides(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from marginalia import jobs

    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    course.materials.mkdir(parents=True)
    calls = []

    def notes(course, deck, **kwargs):
        calls.append((deck, kwargs["slides"]))

    monkeypatch.setattr(
        jobs.importlib,
        "import_module",
        lambda name: SimpleNamespace(generate_deck=notes, review_deck=notes),
    )

    async def run():
        runner = JobRunner()
        for kind in ("generate", "review"):
            job = await runner.create(course, kind, decks=["one"], slides=[2])
            await runner.tasks[job["id"]]
            assert runner.get(job["id"])["state"] == "done"
        assert calls == [("one", [2]), ("one", [2])]

    asyncio.run(run())


def test_repeated_owner_task_cancel_keeps_cpu_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    course.materials.mkdir(parents=True)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def render(course, deck, progress):
        calls.append(deck)
        if deck == "one":
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(slides, "render_deck", render)

    async def run():
        runner = JobRunner()
        first = await runner.create(course, "render", decks=["one"])
        first_task = runner.tasks[first["id"]]
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            first_task.cancel()
            await asyncio.sleep(0)
            first_task.cancel()
            second = await runner.create(course, "render", decks=["two"])
            second_task = runner.tasks[second["id"]]
            await asyncio.sleep(0.02)
            assert calls == ["one"] and runner.cpu.locked()
            release.set()
            await asyncio.gather(first_task, second_task)
            assert runner.get(first["id"])["state"] == "cancelled"
            assert calls == ["one", "two"]
        finally:
            release.set()

    asyncio.run(run())
