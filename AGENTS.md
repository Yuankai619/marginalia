# AGENTS.md

Read `docs/architecture.md` first: it is the contract between the frontend, the backend and the data on disk.
If you need to change the contract, change that file in the same PR and say so in the PR body.

## Ground rules

- Course content (`courses/`) is git-ignored and must never be committed: no slides, videos, transcripts, notes.
  Tests use tiny generated fixtures.
- No API keys. Model calls go through the local Claude Code / Codex logins only (see architecture "LLM usage rule").
- UI text and notes are Traditional Chinese (zh-TW); code, identifiers, commits, PR titles in English.
- Match the surrounding code: comment density, naming, idiom. Small focused modules.
- Don't kill processes you didn't start. A long `transcribe` job may be running on this machine; don't start
  another whisper run without being asked (it takes most CPU cores).

## Running

```
pnpm install && (cd server && uv sync)
pnpm dev            # uvicorn :8765 + vite :5173
pnpm build          # static, read-only site in apps/web/dist
cd server && uv run marginalia --help
```

The real course for manual testing lives in the main checkout at `courses/operating-system` (it is not in your
worktree). Point a worktree at it with `MARGINALIA_COURSES=<main checkout>/courses`. Read it; don't modify
`notes/` there unless your task says so.

## Pre-push check

```
pnpm check                         # biome + tsc for apps/web
cd server && uv run ruff check . && uv run pytest -q
```

All green before push. Branches: `feat/<short-topic>`, `fix/<short-topic>`. PR title: Conventional Commits
(`feat(web): …`). PR body in Traditional Chinese: 做了什麼、怎麼試、沒測到什麼.
