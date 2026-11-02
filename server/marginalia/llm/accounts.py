"""Discover locally logged-in model CLIs without exposing credentials."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any


def _masked_email(token: str) -> str | None:
    try:
        payload = token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        email = data.get("email") or data.get("https://api.openai.com/profile", {}).get(
            "email"
        )
        if not isinstance(email, str) or "@" not in email:
            return None
        local, domain = email.split("@", 1)
        return f"{local[:2]}***@{domain}"
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _claude() -> dict[str, Any]:
    logged_in = False
    plan: str | None = None
    try:
        from .claude import _env

        result = subprocess.run(
            ["claude", "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env={**os.environ, **_env()},
        )
        data = json.loads(result.stdout or "{}")
        if not isinstance(data, dict):
            data = {}
        logged_in = bool(
            data.get("loggedIn") or data.get("logged_in") or data.get("authenticated")
        )
        logged_in = (
            logged_in
            and data.get("authMethod") == "claude.ai"
            and data.get("apiProvider", "firstParty") == "firstParty"
        )
        plan = data.get("plan") or data.get("subscriptionType")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return {
        "id": "claude",
        "provider": "claude",
        "label": "Claude",
        "loggedIn": logged_in,
        "models": [
            {"id": x, "label": x.capitalize()} for x in ("opus", "sonnet", "haiku")
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        **({"plan": plan} if plan else {}),
    }


def _codex_dir_config(path: Path) -> dict[str, Any]:
    for name in ("config.toml", "config.json"):
        try:
            content = (path / name).read_bytes()
            data = (
                tomllib.loads(content.decode())
                if name.endswith("toml")
                else json.loads(content)
            )
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, ValueError, tomllib.TOMLDecodeError):
            continue
    return {}


def subscription_auth(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((path / "auth.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("OPENAI_API_KEY"):
        return None
    if data.get("auth_mode") not in {None, "chatgpt"}:
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict) or not all(
        isinstance(tokens.get(key), str) and tokens[key].strip()
        for key in ("id_token", "access_token", "refresh_token")
    ):
        return None
    return data


def _codex() -> list[dict[str, Any]]:
    home = Path.home()
    dirs = [home / ".codex", *sorted(home.glob(".codex-*"))]
    accounts = []
    for path in dirs:
        auth = path / "auth.json"
        if not auth.is_file():
            continue
        data = subscription_auth(path)
        token = data["tokens"]["id_token"] if data else ""
        cfg = _codex_dir_config(path)
        model = cfg.get("model") or cfg.get("model_name") or "gpt-5"
        label = _masked_email(token) or path.name.lstrip(".")
        accounts.append(
            {
                "id": path.name.lstrip("."),
                "provider": "codex",
                "label": label,
                "loggedIn": data is not None,
                "models": [{"id": model, "label": model}],
                "efforts": ["low", "medium", "high"],
            }
        )
    return accounts


def accounts() -> list[dict[str, Any]]:
    return [_claude(), *_codex()]
