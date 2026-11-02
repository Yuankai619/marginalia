from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from marginalia import config
from marginalia.agents import chat, codex_chat
from marginalia.llm import claude
from marginalia.store import Course, read_json


def test_claude_read_permissions_confine_all_tools(tmp_path):
    root = tmp_path / "course"
    root.mkdir()
    (root / "note.md").write_text("fixture")
    outside = tmp_path / "secret.md"
    outside.write_text("outside")
    (root / "escape.md").symlink_to(outside)
    call = claude.Call(
        "question", cwd=root, tools=["Read", "Grep", "Glob"], read_root=root
    )
    options = claude._options(call)
    assert options.allowed_tools == []
    assert options.tools == ["Read", "Grep", "Glob"]

    async def run():
        for name, data in [
            ("Read", {"file_path": str(outside)}),
            ("Read", {"file_path": "../secret.md"}),
            ("Read", {"file_path": "escape.md"}),
            ("Grep", {"pattern": "secret", "path": str(tmp_path)}),
            ("Grep", {"pattern": "secret"}),
            ("Glob", {"pattern": "**/*"}),
            ("Glob", {"pattern": "../*"}),
            ("Glob", {"pattern": str(tmp_path / "*")}),
            ("Bash", {"command": "cat ../secret.md"}),
        ]:
            result = await options.can_use_tool(name, data, None)
            assert result.behavior == "deny", (name, data)
            hook = options.hooks["PreToolUse"][0].hooks[0]
            result = await hook({"tool_name": name, "tool_input": data}, None, None)
            assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert (
            await options.can_use_tool("Read", {"file_path": "note.md"}, None)
        ).behavior == "allow"
        (root / "escape.md").unlink()
        for name, data in [
            ("Grep", {"pattern": "fixture"}),
            ("Glob", {"pattern": "**/*.md"}),
        ]:
            assert (await options.can_use_tool(name, data, None)).behavior == "allow"
        (root / "alias").symlink_to(tmp_path, target_is_directory=True)
        assert (
            await options.can_use_tool("Glob", {"pattern": "**/*"}, None)
        ).behavior == "deny"

    asyncio.run(run())


def setup_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_chat.shutil, "which", lambda name: "/fixture/codex")
    home = tmp_path / "home"
    account = home / ".codex-test"
    account.mkdir(parents=True)
    (account / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "id_token": "fake-id",
                    "access_token": "fake-access",
                    "refresh_token": "fake-refresh",
                },
            }
        )
    )
    (account / "config.toml").write_text('model_provider = "key-provider"')
    monkeypatch.setattr(Path, "home", lambda: home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.setenv(key, "never-pass-this")
    return account


def test_codex_stderr_reasoning_and_context_only_settings(tmp_path, monkeypatch):
    setup_codex(tmp_path, monkeypatch)
    create = asyncio.create_subprocess_exec
    captured = {}

    async def fake(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        root = Path(kwargs["env"]["CODEX_HOME"])
        assert not (root / "config.toml").exists()
        captured["catalog"] = read_json(root / "models.json")
        assert (root / "auth.json").stat().st_mode & 0o777 == 0o600
        script = """
import json,sys
sys.stdin.read()
sys.stderr.write('s' * 300000)
sys.stderr.flush()
for kind, text in [('reasoning','private'), ('agent_message','answer')]:
 print(json.dumps({'type':'item.completed','item':{'type':kind,'text':text}}),flush=True)
print(json.dumps({'type':'response.output_text.delta','delta':'answer'}),flush=True)
"""
        return await create(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(codex_chat.asyncio, "create_subprocess_exec", fake)

    async def run():
        return [
            e
            async for e in codex_chat.stream(
                "selected context", "codex-test", "gpt-5", "medium"
            )
        ]

    result = asyncio.run(asyncio.wait_for(run(), 5))
    assert result == [{"type": "text", "delta": "answer"}, {"type": "done"}]
    args = captured["args"]
    assert "--ignore-user-config" in args and "--ignore-rules" in args
    assert "-" == args[-1] and "selected context" not in args
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
        assert key not in captured["env"]
    for setting in (
        "features.shell_tool=false",
        "features.view_image=false",
        "agents.enabled=false",
        'model_provider="openai"',
        'forced_login_method="chatgpt"',
        "mcp_servers={}",
    ):
        assert setting in args
    model = captured["catalog"]["models"][0]
    assert model["shell_type"] == "disabled"
    assert model["apply_patch_tool_type"] is None
    assert model["experimental_supported_tools"] == []
    assert not Path(captured["env"]["CODEX_HOME"]).exists()


@pytest.mark.parametrize("close", [False, True])
def test_codex_disconnect_reaps_child(tmp_path, monkeypatch, close):
    setup_codex(tmp_path, monkeypatch)
    create = asyncio.create_subprocess_exec
    processes = []

    async def fake(*args, **kwargs):
        proc = await create(
            sys.executable,
            "-c",
            "import json,time; print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'ready'}}), flush=True); time.sleep(60)",
            **kwargs,
        )
        processes.append(proc)
        return proc

    monkeypatch.setattr(codex_chat.asyncio, "create_subprocess_exec", fake)

    async def run():
        events = codex_chat.stream("context", "codex-test", "gpt-5", "medium")
        await anext(events)
        if close:
            await events.aclose()
        else:
            task = asyncio.create_task(anext(events))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert processes[0].returncode is not None

    asyncio.run(asyncio.wait_for(run(), 5))


def test_chat_modes_and_multiturn_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    course.materials.mkdir(parents=True)
    systems, prompts = [], []

    async def fake(call):
        systems.append(call.system)
        prompts.append(call.prompt)
        yield {"type": "text", "delta": "回答"}
        yield {"type": "done"}

    monkeypatch.setattr(chat.claude, "stream", fake)

    async def run():
        for mode in chat.MODES:
            events = [
                e
                async for e in chat.stream(
                    {"course": "demo", "message": "第一輪", "mode": mode}
                )
            ]
            chat_id = events[0]["chatId"]
            await asyncio.sleep(0)
            _ = [
                e
                async for e in chat.stream(
                    {"course": "demo", "chatId": chat_id, "message": "第二輪"}
                )
            ]
            assert read_json(course.chats_dir / f"{chat_id}.json")["mode"] == mode
            assert systems[-1] == systems[-2]
            assert "第一輪" in prompts[-1] and "回答" in prompts[-1]
        assert len(set(systems)) == 3

    asyncio.run(run())


def test_claude_stream_close_closes_sdk_query(monkeypatch):
    closed = []
    paths = []

    async def fake(**kwargs):
        paths.append(Path(kwargs["options"].system_prompt["path"]))
        try:
            yield claude.AssistantMessage(
                content=[claude.TextBlock(text="fixture")], model="fixture"
            )
            await asyncio.Event().wait()
        finally:
            assert paths[0].is_file()
            closed.append(True)

    monkeypatch.setattr(claude, "query", fake)

    async def run():
        events = claude.stream(claude.Call("question", system="private course context"))
        assert (await anext(events))["delta"] == "fixture"
        await events.aclose()
        assert closed and not paths[0].exists()

    asyncio.run(run())


def test_chat_done_is_persisted_and_concurrent_turns_keep_history(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    course.materials.mkdir(parents=True)
    prompts = []

    async def fake(call):
        prompts.append(call.prompt)
        await asyncio.sleep(0)
        yield {"type": "text", "delta": "fixture answer"}
        yield {"type": "done"}

    monkeypatch.setattr(chat.claude, "stream", fake)

    async def turn(message):
        async for event in chat.stream(
            {"course": "demo", "chatId": "same", "message": message}
        ):
            if event["type"] == "done":
                data = read_json(course.chats_dir / "same.json")
                assert data["messages"][-1]["content"] == "fixture answer"
                assert data["messages"][-2]["content"] == message

    async def run():
        await asyncio.gather(turn("first"), turn("second"))
        data = read_json(course.chats_dir / "same.json")
        assert len(data["messages"]) == 4
        assert "first" in prompts[1] and "fixture answer" in prompts[1]

    asyncio.run(run())


def test_codex_large_stdout_answer(tmp_path, monkeypatch):
    setup_codex(tmp_path, monkeypatch)
    create = asyncio.create_subprocess_exec

    async def fake(*args, **kwargs):
        return await create(
            sys.executable,
            "-c",
            "import json,sys; sys.stdin.read(); print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'繁中'*50000}}),flush=True)",
            **kwargs,
        )

    monkeypatch.setattr(codex_chat.asyncio, "create_subprocess_exec", fake)

    async def run():
        return [
            e
            async for e in codex_chat.stream("context", "codex-test", "gpt-5", "medium")
        ]

    events = asyncio.run(asyncio.wait_for(run(), 5))
    assert events[0] == {"type": "text", "delta": "繁中" * 50000}


def test_codex_disconnect_reaps_launcher_descendant(tmp_path, monkeypatch):
    import os
    import signal

    setup_codex(tmp_path, monkeypatch)
    create = asyncio.create_subprocess_exec
    processes = []
    pidfile = tmp_path / "child.pid"
    script = """
import json,os,signal,subprocess,sys,time
child = subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'])
open(sys.argv[1],'w').write(str(child.pid))
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'ready'}}), flush=True)
time.sleep(60)
"""

    async def fake(*args, **kwargs):
        proc = await create(sys.executable, "-c", script, str(pidfile), **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(codex_chat.asyncio, "create_subprocess_exec", fake)

    async def run():
        events = codex_chat.stream("context", "codex-test", "gpt-5", "medium")
        try:
            await anext(events)
            await events.aclose()
            assert processes[0].returncode is not None
            # A killed orphan may briefly remain as a zombie until PID 1 reaps it.
            stat = Path(f"/proc/{pidfile.read_text()}/stat")
            assert not stat.exists() or stat.read_text().split()[2] == "Z"
        finally:
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    asyncio.run(asyncio.wait_for(run(), 6))


def test_codex_preserves_refreshed_subscription_auth(tmp_path, monkeypatch):
    account = setup_codex(tmp_path, monkeypatch)
    create = asyncio.create_subprocess_exec

    async def fake(*args, **kwargs):
        path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
        data = json.loads(path.read_text())
        data["tokens"]["refresh_token"] = "rotated-fixture"
        path.write_text(json.dumps(data))
        return await create(
            sys.executable, "-c", "import sys; sys.stdin.read()", **kwargs
        )

    monkeypatch.setattr(codex_chat.asyncio, "create_subprocess_exec", fake)

    async def run():
        return [
            event
            async for event in codex_chat.stream(
                "context", "codex-test", "gpt-5", "medium"
            )
        ]

    asyncio.run(run())
    assert (
        read_json(account / "auth.json")["tokens"]["refresh_token"] == "rotated-fixture"
    )


def test_prompt_builder_receives_mode_and_selected_context(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    course = Course("demo")
    captured = []

    def build(course, mode, **context):
        captured.append((mode, context))
        return "fixture prompt"

    monkeypatch.setitem(
        sys.modules, "marginalia.agents.prompts", SimpleNamespace(build_system=build)
    )
    assert "fixture prompt" in chat._system(
        course, {"deck": "week-1", "slide": 2}, "interview"
    )
    assert captured == [("interview", {"deck": "week-1", "slide": 2})]


def test_text_chat_passes_real_sdk_permission_input_validation(tmp_path, monkeypatch):
    from claude_agent_sdk._internal import client

    class ReachedTransport(Exception):
        pass

    class FixtureTransport:
        def __init__(self, prompt, options):
            assert hasattr(prompt, "__aiter__")
            assert options.can_use_tool is not None

        async def connect(self):
            raise ReachedTransport

    monkeypatch.setattr(client, "SubprocessCLITransport", FixtureTransport)

    async def run():
        events = claude.stream(
            claude.Call("text only", read_root=tmp_path, tools=["Read"])
        )
        with pytest.raises(ReachedTransport):
            await anext(events)

    asyncio.run(run())


def test_manifest_cannot_add_other_course_context(tmp_path, monkeypatch):
    from marginalia.store import write_json

    monkeypatch.setattr(config, "COURSES_DIR", tmp_path)
    other = Course("other")
    write_json(other.deck_dir("private") / "slides.json", [{"title": "outside secret"}])
    course = Course("demo")
    course.materials.mkdir(parents=True)
    called = []

    async def fake(call):
        called.append(call)
        yield {"type": "done"}

    monkeypatch.setattr(chat.claude, "stream", fake)

    async def run():
        for deck in (
            "../../../other/generated/decks/private",
            str(other.deck_dir("private")),
        ):
            write_json(
                course.gen / "manifest.json",
                {
                    "decks": [
                        {"id": deck, "source": "materials/fixture.pdf", "title": "bad"}
                    ],
                    "videos": [],
                },
            )
            with pytest.raises(ValueError):
                await anext(chat.stream({"course": "demo", "message": "question"}))
        write_json(
            course.gen / "manifest.json",
            {"decks": [{"id": "safe", "source": "../other/private.pdf"}], "videos": []},
        )
        with pytest.raises(ValueError):
            await anext(chat.stream({"course": "demo", "message": "question"}))
        assert not called

    asyncio.run(run())


@pytest.mark.parametrize("account", ["claude", "codex-test"])
def test_both_providers_receive_cross_deck_notes_and_transcripts(
    course, monkeypatch, account
):
    from marginalia.store import write_json

    course.save_manifest(
        {
            "decks": [
                {"id": "first", "source": "materials/first.pdf", "title": "第一週"},
                {"id": "second", "source": "materials/second.pdf", "title": "第二週"},
            ],
            "videos": [
                {"id": "lecture", "source": "materials/lecture.mp4"},
                {"id": "partial", "source": "materials/partial.mp4"},
            ],
        }
    )
    write_json(
        course.deck_path("first", "slides.json"),
        [
            {"index": 1, "title": "目前頁", "text": "CURRENT_TEXT"},
            {"index": 2, "title": "其他頁", "text": "OTHER_PAGE_BODY"},
        ],
    )
    write_json(
        course.deck_path("second", "slides.json"),
        [
            {
                "index": 31,
                "title": "另一份簡報",
                "text": "CROSS_DECK_BODY",
                "speakerNotes": "SPEAKER_NOTES",
            },
        ],
    )
    course.note_path("first", 2).parent.mkdir(parents=True, exist_ok=True)
    course.note_path("first", 2).write_text("OTHER_PAGE_NOTE")
    course.note_path("second", 31).parent.mkdir(parents=True, exist_ok=True)
    course.note_path("second", 31).write_text("CROSS_DECK_NOTE")
    write_json(
        course.video_path("lecture", "transcript.json"),
        {
            "segments": [{"start": 42.5, "end": 44, "text": "TEACHER_TRANSCRIPT"}],
        },
    )
    write_json(
        course.video_path("partial", "transcript.partial.json"),
        {
            "segments": [{"start": 60, "end": 62, "text": "PARTIAL_TRANSCRIPT"}],
        },
    )
    captured = []

    async def fake_claude(call):
        captured.append(call.system)
        yield {"type": "text", "delta": "fixture"}
        yield {"type": "done"}

    async def fake_codex(prompt, *args):
        captured.append(prompt)
        yield {"type": "text", "delta": "fixture"}
        yield {"type": "done"}

    monkeypatch.setattr(chat.claude, "stream", fake_claude)
    monkeypatch.setattr(chat.codex_chat, "stream", fake_codex)
    context = {"deck": "first", "slide": 1}

    async def run():
        return [
            event
            async for event in chat.stream(
                {
                    "course": course.id,
                    "account": account,
                    "message": "說明第二週、其他頁筆記和老師的說法",
                    "context": context,
                }
            )
        ]

    asyncio.run(run())
    system = chat._system(course, context)
    assert captured[0].startswith(system)
    for marker in (
        "CURRENT_TEXT",
        "OTHER_PAGE_BODY",
        "CROSS_DECK_BODY",
        "SPEAKER_NOTES",
        "OTHER_PAGE_NOTE",
        "CROSS_DECK_NOTE",
        "TEACHER_TRANSCRIPT",
        "PARTIAL_TRANSCRIPT",
        "video:lecture?t=42",
        "video:partial?t=60",
    ):
        assert marker in captured[0]


def test_shared_course_prompt_has_one_budget_and_keeps_current_context(course):
    from marginalia.agents import prompts
    from marginalia.store import write_json

    course.save_manifest(
        {
            "decks": [
                {"id": "first", "source": "materials/first.pdf"},
                {"id": "second", "source": "materials/second.pdf"},
            ],
            "videos": [{"id": "lecture", "source": "materials/lecture.mp4"}],
        }
    )
    write_json(
        course.deck_path("first", "slides.json"),
        [
            {
                "index": 1,
                "title": "目前頁",
                "text": "CURRENT_PRIORITY" + "甲" * 200_000,
                "speakerNotes": "SPEAKER_PRIORITY" + "註" * 20_000,
            },
        ],
    )
    write_json(
        course.deck_path("second", "slides.json"),
        [
            {
                "index": 1,
                "title": "第二週",
                "text": "OTHER_DECK_PRIORITY" + "乙" * 200_000,
            },
        ],
    )
    write_json(
        course.video_path("lecture", "transcript.json"),
        {
            "segments": [
                {"start": 0, "end": 1, "text": "舊" * 200_000},
                {"start": 900, "end": 905, "text": "CURRENT_TRANSCRIPT_PRIORITY"},
            ],
        },
    )
    write_json(
        course.path("generated", "alignment.json"),
        {
            "segments": [
                {
                    "video": "lecture",
                    "deck": "first",
                    "slide": 1,
                    "start": 900,
                    "end": 910,
                }
            ],
        },
    )
    course.note_path("first", 1).parent.mkdir(parents=True, exist_ok=True)
    course.note_path("first", 1).write_text("NOTE_PRIORITY" + "筆" * 50_000)
    system = prompts.build_system(
        course,
        "review",
        "first",
        1,
        selection={"text": "SELECTED_PRIORITY" + "選" * 10_000},
        region={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
    )
    assert len(system) <= prompts.PROMPT_CHARS
    assert all(
        marker in system
        for marker in (
            "CURRENT_PRIORITY",
            "OTHER_DECK_PRIORITY",
            "SELECTED_PRIORITY",
            "CURRENT_TRANSCRIPT_PRIORITY",
            "NOTE_PRIORITY",
            "SPEAKER_PRIORITY",
        )
    )
    assert "截斷" in system


def test_formal_preload_reuses_short_page_budget_for_long_transcript(course):
    from marginalia.agents import prompts
    from marginalia.store import write_json

    course.save_manifest(
        {
            "decks": [{"id": "short", "source": "materials/short.pdf"}],
            "videos": [{"id": "lecture", "source": "materials/lecture.mp4"}],
        }
    )
    write_json(
        course.deck_path("short", "slides.json"),
        [
            {"index": index, "title": f"Page {index}", "text": "短" * 60}
            for index in range(1, 101)
        ],
    )
    write_json(
        course.video_path("lecture", "transcript.json"),
        {
            "segments": [
                {
                    "start": 0,
                    "end": 60,
                    "text": "前" * 20_000 + "LATE_TRANSCRIPT_CONTEXT" + "後" * 40_000,
                }
            ],
        },
    )
    material = prompts._course_material(course, None, 50_000)
    assert "LATE_TRANSCRIPT_CONTEXT" in material
    assert 49_000 <= len(material) <= 50_000
