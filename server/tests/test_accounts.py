from __future__ import annotations

import json

from marginalia.llm import accounts


def test_codex_account_never_exposes_token(tmp_path, monkeypatch):
    home = tmp_path / "home"
    codex = home / ".codex-test"
    codex.mkdir(parents=True)
    secret = "very-secret-token"
    (codex / "auth.json").write_text(json.dumps({"tokens": {"id_token": secret}}))
    monkeypatch.setattr(accounts.Path, "home", lambda: home)
    monkeypatch.setattr(accounts, "_claude", lambda: {"id": "claude"})
    result = accounts.accounts()
    assert result[1]["id"] == "codex-test"
    assert secret not in repr(result)
