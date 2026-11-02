import asyncio
import os
import stat

import pytest

from marginalia.llm import codex

FAKE = """#!/bin/sh
# records argv and env, answers with stdin reversed into the -o file
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift;; esac
  shift
done
printf '%s|%s|%s' "$CODEX_HOME" "${OPENAI_API_KEY:-none}" "$(cat)" > "$out"
"""


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "codex"
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    return tmp_path


def test_available_needs_login(fake_codex):
    home = fake_codex / "home"
    home.mkdir()
    assert not codex.available(home)
    (home / "auth.json").write_text("{}")
    assert codex.available(home)


def test_complete_uses_codex_home_and_drops_api_key(fake_codex):
    out = asyncio.run(codex.complete("你好", codex_home=fake_codex / "home"))
    assert out == f"{fake_codex / 'home'}|none|你好"


def test_complete_reports_failure(fake_codex):
    (fake_codex / "bin" / "codex").write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 3\n")
    with pytest.raises(RuntimeError, match="not logged in"):
        asyncio.run(codex.complete("x"))
