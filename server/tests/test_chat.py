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
