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


def test_local_api_rejects_untrusted_host(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    assert (
        client.get("/api/health", headers={"Host": "attacker.example"}).status_code
        == 400
    )


def test_html_file_is_downloaded(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    (course.materials / "unsafe.html").write_text("<script>1</script>")
    client = TestClient(create_app(JobRunner()))
    response = client.get(f"/files/{course.id}/materials/unsafe.html")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


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


def test_symlink_course_root_is_rejected(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (course.dir.parent / "alias").symlink_to(outside, target_is_directory=True)
    client = TestClient(create_app(JobRunner()))
    assert client.get("/files/alias/secret.txt").status_code == 404
    assert client.put("/api/courses/alias", json={"title": "bad"}).status_code == 404
    assert "alias" not in [c["id"] for c in client.get("/api/courses").json()]


def test_course_subtree_symlinks_cannot_read_or_write(tmp_path, monkeypatch):
    import pytest

    course = make_course(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "001.md").write_text("secret")
    client = TestClient(create_app(JobRunner()))
    for path in (course.notes_dir / "week-1", course.chats_dir, course.gen / "reviews"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(outside, target_is_directory=True)
        assert client.get("/api/courses/demo/decks/week-1/notes/1").status_code == 404
        assert (
            client.put(
                "/api/courses/demo/decks/week-1/notes/1", json={"markdown": "bad"}
            ).status_code
            == 404
        )
        assert client.get("/api/courses/demo/chats").status_code == 404
        path.unlink()
    for path in (course.materials / "linked", course.materials / "dangling.pdf"):
        path.symlink_to(outside / "missing.pdf")
        response = client.post(
            "/api/courses/demo/upload", files={"files": ("dangling.pdf", b"bad")}
        )
        assert response.status_code == 404
        assert not (outside / "missing.pdf").exists()
        path.unlink()
    assert (outside / "001.md").read_text() == "secret"
    with pytest.raises(ValueError):
        from marginalia.course_access import confined

        confined(course.dir / "../outside", course.dir)


def test_upload_uses_multipart_folder_and_preserves_existing_file(
    tmp_path, monkeypatch
):
    course = make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    for body in (b"one", b"two"):
        response = client.post(
            "/api/courses/demo/upload",
            data={"folder": "week-1"},
            files={"files": ("fixture.txt", body)},
        )
        assert response.status_code == 200
        assert response.json()["saved"][0].startswith("materials/week-1/")
    assert (course.materials / "week-1/fixture.txt").read_bytes() == b"one"
    assert (course.materials / "week-1/fixture-2.txt").read_bytes() == b"two"


def test_side_effect_origins_are_checked_before_handlers(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    for origin in (
        "https://evil.example",
        "null",
        "http://localhost:9999",
        "http://localhost:5173.evil.example",
    ):
        for method, path in (
            ("POST", "/api/courses/demo/scan"),
            ("POST", "/api/jobs/missing/cancel"),
            ("PUT", "/api/courses/demo"),
            ("DELETE", "/api/courses/demo"),
        ):
            assert (
                client.request(method, path, headers={"Origin": origin}).status_code
                == 403
            )
    for origin in (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://testserver",
    ):
        assert (
            client.post(
                "/api/courses/demo/scan", headers={"Origin": origin}
            ).status_code
            == 200
        )
    assert (
        client.get(
            "/api/health", headers={"Origin": "https://evil.example"}
        ).status_code
        == 200
    )


def test_invalid_chat_mode_rejected(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    client = TestClient(create_app(JobRunner()))
    assert (
        client.post(
            "/api/agents/chat",
            json={"course": "demo", "message": "test", "mode": "bad"},
        ).status_code
        == 422
    )


def test_chat_errors_do_not_expose_cli_details(tmp_path, monkeypatch):
    from marginalia import api

    make_course(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "accounts", lambda: [{"id": "claude", "loggedIn": True}])

    async def fail(body):
        raise RuntimeError("secret-token /private/path")
        yield

    monkeypatch.setattr(api.chat, "stream", fail)
    response = TestClient(create_app(JobRunner())).post(
        "/api/agents/chat", json={"course": "demo", "message": "test"}
    )
    assert "secret-token" not in response.text and "private/path" not in response.text
    assert '"type": "error"' in response.text


def test_asgi_send_disconnect_closes_chat_before_return(tmp_path, monkeypatch):
    import json

    import pytest
    from starlette.requests import ClientDisconnect

    from marginalia import api

    make_course(tmp_path, monkeypatch)
    monkeypatch.setattr(api, "accounts", lambda: [{"id": "claude", "loggedIn": True}])
    closed = []

    async def provider(call):
        try:
            yield {"type": "text", "delta": "fixture"}
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    monkeypatch.setattr(api.chat.claude, "stream", provider)
    app = create_app(JobRunner())
    body = json.dumps({"course": "demo", "message": "question"}).encode()

    async def run():
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(event):
            if event["type"] == "http.response.body" and b'"type": "text"' in event.get(
                "body", b""
            ):
                raise OSError("fixture disconnect")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/agents/chat",
            "raw_path": b"/api/agents/chat",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
        }
        with pytest.raises((ClientDisconnect, OSError)):
            await app(scope, receive, send)
        assert closed == [True]

    asyncio.run(asyncio.wait_for(run(), 5))


def test_upload_does_not_follow_internal_dangling_destination(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    target = course.materials / "untouched.txt"
    (course.materials / "fixture.txt").symlink_to(target)
    response = TestClient(create_app(JobRunner())).post(
        "/api/courses/demo/upload", files={"files": ("fixture.txt", b"fixture")}
    )
    assert response.status_code == 200
    assert response.json()["saved"] == ["materials/fixture-2.txt"]
    assert not target.exists()


def test_slow_account_checks_do_not_block_other_requests(tmp_path, monkeypatch):
    import threading

    from fastapi import HTTPException

    from marginalia import api

    make_course(tmp_path, monkeypatch)

    async def run(path):
        entered, release = threading.Event(), threading.Event()

        def accounts():
            entered.set()
            assert release.wait(3)
            return [{"id": "claude", "loggedIn": False}]

        monkeypatch.setattr(api, "accounts", accounts)
        app = create_app(JobRunner())
        endpoint = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", None) == path
        )
        health = next(
            route.endpoint
            for route in app.routes
            if getattr(route, "path", None) == "/api/health"
        )
        arguments = (
            {"body": {"course": "demo", "message": "question"}}
            if path.endswith("chat")
            else {}
        )
        task = asyncio.create_task(endpoint(**arguments))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(health(), 0.5)
            assert response["mode"] == "local" and not task.done()
        finally:
            release.set()
            try:
                await task
            except HTTPException as exc:
                assert exc.status_code == 422

    asyncio.run(run("/api/agents/accounts"))
    asyncio.run(run("/api/agents/chat"))


def test_configured_origins_allow_tailscale_proxy_and_reject_other_sources(
    tmp_path, monkeypatch
):
    make_course(tmp_path, monkeypatch)
    monkeypatch.setenv(
        "MARGINALIA_ALLOWED_ORIGINS",
        " http://100.81.100.96:5173, ,http://localhost:5173, ",
    )
    client = TestClient(create_app(JobRunner()))
    for origin in ("http://100.81.100.96:5173", "http://localhost:5173"):
        response = client.post(
            "/api/courses/demo/scan",
            headers={"Host": "100.81.100.96:5173", "Origin": origin},
        )
        assert response.status_code == 200
    for origin in (
        "http://100.81.100.96:5174",
        "https://100.81.100.96:5173",
        "http://100.81.100.97:5173",
        "http://100.81.100.96.evil.example:5173",
        "http://127.0.0.1:5173",
        "null",
    ):
        assert (
            client.post(
                "/api/courses/demo/scan", headers={"Origin": origin}
            ).status_code
            == 403
        )
    assert (
        client.get("/api/health", headers={"Host": "100.81.100.97:5173"}).status_code
        == 400
    )
    assert (
        client.get("/api/health", headers={"Host": "attacker.example"}).status_code
        == 400
    )


def test_empty_origin_setting_keeps_same_origin_and_cli_requests(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    monkeypatch.setenv("MARGINALIA_ALLOWED_ORIGINS", " , ")
    client = TestClient(create_app(JobRunner()))
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        assert (
            client.post(
                "/api/courses/demo/scan", headers={"Origin": origin}
            ).status_code
            == 403
        )
    assert (
        client.post(
            "/api/courses/demo/scan", headers={"Origin": "http://testserver"}
        ).status_code
        == 200
    )
    assert client.post("/api/courses/demo/scan").status_code == 200


def test_default_origins_reject_unconfigured_tailscale(tmp_path, monkeypatch):
    make_course(tmp_path, monkeypatch)
    monkeypatch.delenv("MARGINALIA_ALLOWED_ORIGINS", raising=False)
    client = TestClient(create_app(JobRunner()))
    assert (
        client.post(
            "/api/courses/demo/scan", headers={"Origin": "http://100.81.100.96:5173"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/health", headers={"Host": "100.81.100.96:5173"}).status_code
        == 400
    )


def test_invalid_origin_configuration_fails_at_startup(monkeypatch):
    import pytest

    for value in (
        "*",
        "null",
        "http://*.example",
        "http://example/path",
        "http://example/",
        "http://example:bad",
        "http://user:password@example",
    ):
        monkeypatch.setenv("MARGINALIA_ALLOWED_ORIGINS", value)
        with pytest.raises(ValueError, match="MARGINALIA_ALLOWED_ORIGINS"):
            create_app(JobRunner())


def test_store_validation_errors_are_http_errors(tmp_path, monkeypatch):
    course = make_course(tmp_path, monkeypatch)
    manifest = course.manifest()
    manifest["videos"] = [{"id": "clip", "source": "materials/clip.mp4"}]
    course.save_manifest(manifest)
    client = TestClient(create_app(JobRunner()))
    for deck in ("week.1", "-week-1"):
        assert client.get(f"/api/courses/demo/decks/{deck}").status_code == 404
        assert client.get(f"/api/courses/demo/decks/{deck}/notes/1").status_code == 404
    assert (
        client.get("/api/courses/demo/videos/clip.invalid/transcript").status_code
        == 404
    )
    for index in (0, -1):
        response = client.get(f"/api/courses/demo/decks/week-1/notes/{index}")
        assert response.status_code == 422 and isinstance(
            response.json()["detail"], str
        )
        assert (
            client.put(
                f"/api/courses/demo/decks/week-1/notes/{index}",
                json={"markdown": "fixture"},
            ).status_code
            == 422
        )
    for body in (
        {"video": "clip.invalid", "start": 0, "end": 1},
        {"video": "clip", "deck": "week.1", "start": 0, "end": 1},
    ):
        response = client.put("/api/courses/demo/alignment/segments", json=body)
        assert response.status_code == 422 and isinstance(
            response.json()["detail"], str
        )
