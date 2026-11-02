import asyncio
import json
import os
import stat

import pytest

from marginalia.llm import codex

FAKE = """#!/bin/sh
# records argv and env, answers with what it saw into the -o file
args="$*"
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift;; esac
  shift
done
printf '%s|%s|%s|%s' "$CODEX_HOME" "${OPENAI_API_KEY:-none}${SECRET_TOKEN:-}" "$args" "$(cat)" > "$out"
touch "$CODEX_HOME/ran"
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "codex"
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
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
    (home.parent / "bin" / "codex").write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 3\n")
    with pytest.raises(RuntimeError, match="not logged in"):
        asyncio.run(codex.complete("x", codex_home=home))
