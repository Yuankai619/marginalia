import asyncio
import json
import os
import stat

import pytest

from marginalia.llm import codex

FAKE = """#!/bin/sh
# `debug prompt-input` prints the tool list baked in below; `exec` records argv and env into the -o file
if [ "$1" = debug ]; then
  printf '%s' '[{"type":"additional_tools","tools":[{"type":"namespace","name":"functions","tools":[TOOLS]}]}]'
  exit 0
fi
args="$*"
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift;; esac
  shift
done
printf '%s|%s|%s|%s' "$CODEX_HOME" "${OPENAI_API_KEY:-none}${SECRET_TOKEN:-}" "$args" "$(cat)" > "$out"
touch "$CODEX_HOME/ran"
"""


INERT = '{"type":"custom","name":"exec"},{"type":"function","name":"wait"}'


def install_fake(bin_dir, tools: str = INERT) -> None:
    exe = bin_dir / "codex"
    exe.write_text(FAKE.replace("TOOLS", tools))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(codex, "_verified", False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    install_fake(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("SECRET_TOKEN", "tok-should-not-leak")
    h = tmp_path / "home"
    h.mkdir()
    (h / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": {}}))
    return h


def test_available_needs_a_subscription_login(home):
    assert codex.available(home)
    (home / "auth.json").write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "fake-fixture-key"}))
    assert not codex.available(home)
    (home / "auth.json").unlink()
    assert not codex.available(home)


def test_api_key_login_is_refused_before_codex_starts(home):
    (home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": "fake-fixture-key"}))
    with pytest.raises(RuntimeError, match="API key"):
        asyncio.run(codex.complete("x", codex_home=home))
    assert not (home / "ran").exists()


def test_complete_runs_without_tools_or_inherited_secrets(home):
    out = asyncio.run(codex.complete("你好", codex_home=home))
    got_home, secrets, args, prompt = out.split("|")
    assert got_home == str(home) and secrets == "none" and prompt == "你好"
    assert 'forced_login_method="chatgpt"' in args and "--ignore-user-config" in args
    for feature in ("shell_tool", "unified_exec", "code_mode_host", "view_image"):
        assert f"--disable {feature}" in args


def test_complete_reports_failure(home):
    asyncio.run(codex.verify_tools())
    (home.parent / "bin" / "codex").write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 3\n")
    with pytest.raises(RuntimeError, match="not logged in"):
        asyncio.run(codex.complete("x", codex_home=home))


@pytest.mark.parametrize("tools", [INERT + ',{"type":"function","name":"shell"}', ""])
def test_codex_refuses_to_run_when_it_would_get_tools(home, monkeypatch, tools):
    install_fake(home.parent / "bin", tools)  # a CLI upgrade added a tool, or stopped listing them: fail closed
    with pytest.raises(RuntimeError, match="不使用 Codex"):
        asyncio.run(codex.complete("x", codex_home=home))
    assert not (home / "ran").exists()


def test_tool_names_walks_namespaces():
    data = [
        {"type": "message"},
        {"type": "additional_tools", "tools": [{"type": "namespace", "name": "functions", "tools": [{"name": "exec"}]}, {"name": "x"}]},
    ]
    assert codex.tool_names(data) == ["functions.exec", "x"]
