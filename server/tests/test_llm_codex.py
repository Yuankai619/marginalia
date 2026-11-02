import asyncio
import json
import os
import stat

import pytest

from marginalia.llm import codex

FAKE = """#!/bin/sh
# `debug prompt-input` prints the tool list baked in below and exits with DEBUG_EXIT; `exec` records argv and env
# into the -o file, or fails with EXEC_FAIL
if [ "$1" = debug ]; then
  DEBUG_HOOK
  printf '%s' '[{"type":"additional_tools","tools":[{"type":"namespace","name":"functions","tools":[TOOLS]}]}]'
  exit DEBUG_EXIT
fi
EXEC_FAIL
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


def install_fake(bin_dir, tools: str = INERT, debug_exit: int = 0, debug_hook: str = ":", exec_fail: str = ":") -> None:
    exe = bin_dir / "codex"
    script = FAKE.replace("TOOLS", tools).replace("DEBUG_EXIT", str(debug_exit))
    exe.write_text(script.replace("DEBUG_HOOK", debug_hook).replace("EXEC_FAIL", exec_fail))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def home(tmp_path, monkeypatch):
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
    install_fake(home.parent / "bin", exec_fail="echo 'not logged in' >&2; exit 3")
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


def test_every_call_is_checked_so_an_upgrade_that_adds_tools_is_caught(home):
    asyncio.run(codex.complete("first", codex_home=home))
    (home / "ran").unlink()
    install_fake(home.parent / "bin", INERT + ',{"type":"function","name":"shell"}')  # the CLI was upgraded
    with pytest.raises(RuntimeError, match="shell"):
        asyncio.run(codex.complete("second", codex_home=home))
    assert not (home / "ran").exists()


def test_check_that_exits_nonzero_is_a_failure_even_with_clean_output(home):
    install_fake(home.parent / "bin", debug_exit=3)
    with pytest.raises(RuntimeError, match="結束碼 3"):
        asyncio.run(codex.complete("x", codex_home=home))
    assert not (home / "ran").exists()


def test_executable_swapped_during_the_check_is_refused(home):
    install_fake(home.parent / "bin", debug_hook='echo "# changed" >> "$0"')
    with pytest.raises(RuntimeError, match="被換掉"):
        asyncio.run(codex.complete("x", codex_home=home))
    assert not (home / "ran").exists()


def test_the_checked_executable_is_the_one_that_runs(home):
    out = asyncio.run(codex.complete("x", codex_home=home))
    exe, _ = codex.executable()
    assert exe == str((home.parent / "bin" / "codex").resolve())
    assert "exec" in out.split("|")[2]
