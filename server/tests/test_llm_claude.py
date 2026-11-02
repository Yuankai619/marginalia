import asyncio
from pathlib import Path

from marginalia.llm import claude


def test_system_prompt_goes_through_a_private_file_and_no_tools(monkeypatch):
    seen = {}

    async def fake_query(prompt, options):
        path = Path(options.system_prompt["path"])
        seen.update(text=path.read_text("utf-8"), mode=path.parent.stat().st_mode & 0o777, opts=options)
        return
        yield

    monkeypatch.setattr(claude, "query", fake_query)
    asyncio.run(claude.complete(claude.Call(prompt="hi", system="大綱" * 100_000)))
    assert seen["text"] == "大綱" * 100_000 and seen["mode"] == 0o700
    assert seen["opts"].tools == [] and "Agent" in seen["opts"].disallowed_tools
    assert seen["opts"].env["ANTHROPIC_API_KEY"] == "" and seen["opts"].env["ANTHROPIC_BASE_URL"] == ""
    assert not Path(seen["opts"].system_prompt["path"]).exists()  # cleaned up after the call
