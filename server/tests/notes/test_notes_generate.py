import pytest

from marginalia.llm import claude
from marginalia.notes import generate, notefile
from marginalia.notes.material import Gatherer, clock, render


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def fake(call):
        seen.append(call)
        if "第 2 頁「System Calls」" in call.prompt:
            return "```markdown\n# System Calls\n\nsystem call 是進入 kernel 的門 [9:99](video:v1?t=64)。\n```"
        return "kernel 管理硬體 [00:30](video:v1?t=30)。"

    monkeypatch.setattr(claude, "complete", fake)
    return seen


def test_clock():
    assert clock(64) == "01:04"
    assert clock(3725.9) == "1:02:05"


def test_material_has_ranges_and_timed_transcript(course):
    m = Gatherer(course, "d1").get(2)
    assert [(r["start"], r["end"]) for r in m.ranges] == [(60.0, 120.0)]
    assert [ln["start"] for ln in m.lines] == [64.0, 90.0]
    text = render(m)
    assert "[v1 t=64 01:04] a system call is like a door into the kernel" in text
    assert "前一頁：Intro；後一頁：Backup Slide" in text
    assert "Explain traps." in text


def test_partial_transcript_is_flagged(course):
    (course.video_dir("v1") / "transcript.json").unlink()
    from marginalia.store import write_json

    write_json(course.video_dir("v1") / "transcript.partial.json", {"segments": [{"start": 2.0, "end": 8.0, "text": "hi"}]})
    m = Gatherer(course, "d1").get(1)
    assert m.partial and "還在轉錄中" in render(m)


def test_generate_writes_notes_and_skips_unshown_slide(course, calls):
    out = generate.generate_deck(course, "d1")
    assert out == {"generated": [1, 2], "skipped": [3], "failed": {}}
    assert len(calls) == 2  # slide 3 was never on screen: no model call

    meta, body = notefile.read(course.note_path("d1", 2))
    assert meta["status"] == "generated" and meta["title"] == "System Calls" and meta["sources"] == ["v1@60-120"]
    assert body == "system call 是進入 kernel 的門 [01:04](video:v1?t=64)。"  # fence + H1 stripped, label fixed
    assert notefile.read(course.note_path("d1", 3))[0]["status"] == "skipped"


def test_resume_only_fills_missing_and_edited_is_kept(course, calls):
    generate.generate_deck(course, "d1")
    path = course.note_path("d1", 1)
    meta, _ = notefile.read(path)
    notefile.write(path, {**meta, "status": "edited"}, "我自己寫的")
    course.note_path("d1", 2).unlink()
    calls.clear()

    assert generate.generate_deck(course, "d1")["generated"] == [2]
    assert generate.generate_deck(course, "d1", slides=[1, 2])["generated"] == [2]
    assert notefile.read(path)[1] == "我自己寫的"

    generate.generate_deck(course, "d1", slides=[1], force=True)
    assert notefile.read(path)[0]["status"] == "generated"


def test_model_skip_reply(course, monkeypatch):
    async def fake(call):
        return "SKIP: 老師只是翻過這頁。\n多的字"

    monkeypatch.setattr(claude, "complete", fake)
    generate.generate_deck(course, "d1", slides=[1])
    meta, body = notefile.read(course.note_path("d1", 1))
    assert meta["status"] == "skipped" and body == "老師只是翻過這頁。"


def test_failure_raises_after_other_slides_are_written(course, monkeypatch):
    async def fake(call):
        if "第 1 頁" in call.prompt:
            raise RuntimeError("boom")
        return "內容"

    monkeypatch.setattr(claude, "complete", fake)
    with pytest.raises(RuntimeError, match="第 1 頁產生失敗：boom"):
        generate.generate_deck(course, "d1")
    assert notefile.read(course.note_path("d1", 2))[1] == "內容"
    assert notefile.read(course.note_path("d1", 1)) is None


def test_unaligned_deck_writes_from_slides_without_links(course, calls):
    from marginalia.store import write_json

    write_json(course.gen / "alignment.json", {"segments": []})
    generate.generate_deck(course, "d1", slides=[3])
    assert "不要附任何時間點連結" in calls[0].prompt
    assert notefile.read(course.note_path("d1", 3))[0]["status"] == "generated"


def test_bad_slide_index(course, calls):
    with pytest.raises(IndexError):
        generate.generate_deck(course, "d1", slides=[9])


def test_notefile_roundtrip(tmp_path):
    p = tmp_path / "001.md"
    notefile.write(p, {"slide": 1, "title": "核心", "status": "generated", "sources": ["v@1-2"]}, "正文\n\n## 補充\n- a")
    meta, body = notefile.read(p)
    assert meta["title"] == "核心" and body == "正文\n\n## 補充\n- a"
    assert notefile.parse("no front matter") == ({}, "no front matter")


def test_short_flash_goes_to_the_writer_not_auto_skip(course, calls):
    from marginalia.store import write_json

    al = course.alignment()
    al["segments"].append({"video": "v1", "start": 200.0, "end": 203.0, "deck": "d1", "slide": 3, "score": 0.5, "manual": False})
    write_json(course.gen / "alignment.json", al)
    generate.generate_deck(course, "d1", slides=[3])
    assert len(calls) == 1 and "unrelated chat after class" in calls[0].prompt


def test_edited_during_generation_is_kept(course, monkeypatch):
    path = course.note_path("d1", 1)

    async def user_edits_meanwhile(call):
        notefile.write(path, {"slide": 1, "status": "edited"}, "使用者剛改的")
        return "模型的版本"

    monkeypatch.setattr(claude, "complete", user_edits_meanwhile)
    generate.generate_deck(course, "d1", slides=[1])
    assert notefile.read(path)[1] == "使用者剛改的"
