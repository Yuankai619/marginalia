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
