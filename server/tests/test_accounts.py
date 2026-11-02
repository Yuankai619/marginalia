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


def test_codex_only_accepts_subscription_auth(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    fixtures = [
        '{"OPENAI_API_KEY":"fake-key"}',
        "{}",
        "broken",
        "null",
        "[]",
        '{"tokens":null}',
        '{"tokens":{"id_token":"fake"}}',
        json.dumps(
            {
                "auth_mode": "apikey",
                "tokens": {"id_token": "i", "access_token": "a", "refresh_token": "r"},
            }
        ),
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {"id_token": "i", "access_token": "a", "refresh_token": "r"},
            }
        ),
    ]
    for n, fixture in enumerate(fixtures):
        directory = home / f".codex-{n}"
        directory.mkdir()
        (directory / "auth.json").write_text(fixture)
    monkeypatch.setattr(accounts.Path, "home", lambda: home)
    results = accounts._codex()
    assert [a["loggedIn"] for a in results] == [False] * 8 + [True]
    assert "fake-key" not in repr(results)


def test_claude_only_accepts_subscription_and_clears_provider_env(monkeypatch):
    from types import SimpleNamespace

    from marginalia.llm.claude import _env

    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.setenv(key, "fixture")
        assert _env()[key] == ""
    method = "api_key"

    def status(*args, **kwargs):
        assert kwargs["env"]["ANTHROPIC_AUTH_TOKEN"] == ""
        return SimpleNamespace(
            stdout=json.dumps(
                {"loggedIn": True, "authMethod": method, "apiProvider": "firstParty"}
            )
        )

    monkeypatch.setattr(accounts.subprocess, "run", status)
    assert not accounts._claude()["loggedIn"]
    method = "claude.ai"
    assert accounts._claude()["loggedIn"]
