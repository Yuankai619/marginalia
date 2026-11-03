"""SKIP is a request to check the slide without unrelated classroom context, not a missing note."""

import json

import pytest
from PIL import Image

from marginalia.export import export_courses
from marginalia.llm import claude
from marginalia.notes import generate, notefile, review
from marginalia.notes.material import Gatherer
from marginalia.store import read_json, write_json

BODY = ('> [!IMPORTANT]\n> ==system call 透過 trap 進入 kernel==。\n\n'
        '[01:04](video:v1?t=64 "課堂來源")\n\n[來源][source]\n\n[source]: video:v1?t=64\n\n'
        '<a href="video:v1?t=64">01:04</a>')


@pytest.fixture
def skimmed(course, monkeypatch):
    for i in (1, 3):
        notefile.write(course.note_path("d1", i), {"status": "edited"}, "保留")
    calls = []

    async def writer(call):
        calls.append(call)
        return BODY if generate.NO_LINKS_RULE in call.prompt else "SKIP: 老師在說明作業繳交規則。"

    monkeypatch.setattr(claude, "complete", writer)
    return calls


def test_skip_uses_slide_only_material_and_exports_notes(course, skimmed, tmp_path_factory):
    original = Gatherer(course, "d1").get(2)
    assert generate.generate_deck(course, "d1")["generated"] == [2]
    assert len(skimmed) == 2
    assert "a system call is like a door" in skimmed[0].prompt
    assert "a system call is like a door" not in skimmed[1].prompt
    assert "v1 t=64" not in skimmed[1].prompt and "t=60" not in skimmed[1].prompt
    assert "對齊結果裡這頁沒有出現在任何影片上" not in skimmed[1].prompt
    assert "Explain traps." in skimmed[1].prompt and generate.UNTAUGHT_RULE in skimmed[1].prompt
    assert "不要捏造「老師說」" in skimmed[1].prompt
    front, body = notefile.read(course.note_path("d1", 2))
    assert front["untaught"] is True and front["sources"] == [] and front["inputs"] == original.inputs
    assert body.startswith(generate.UNTAUGHT_NOTICE) and "video:" not in body
    out = tmp_path_factory.mktemp("skimmed-export") / "snapshot"
    export_courses(out, [course.id])
    exported = json.loads((out / "data/demo/decks/d1.json").read_text())["notes"]["2"]
    assert exported["markdown"].strip() == body and exported["meta"]["status"] == "generated"
    skimmed.clear()
    assert generate.generate_deck(course, "d1")["generated"] == [] and not skimmed


@pytest.mark.parametrize("slide", [
    {"title": "", "text": "", "speakerNotes": ""},
    {"title": "System Calls", "text": "System Calls", "speakerNotes": ""},
    {"title": "Chapter 2", "text": "Chapter 2\nProcess Management", "speakerNotes": ""},
])
def test_blank_title_and_chapter_pages_can_still_skip(course, skimmed, monkeypatch, slide):
    slides = course.slides("d1")
    slides[1] = {"index": 2, **slide}
    write_json(course.deck_path("d1", "slides.json"), slides)

    async def classifier(call):
        skimmed.append(call)
        return "SKIP: 這頁只有標題或章節分隔，沒有正文。"

    monkeypatch.setattr(claude, "complete", classifier)
    assert generate.generate_deck(course, "d1")["skipped"] == [2]
    assert len(skimmed) == 2 and generate.UNTAUGHT_RULE in skimmed[1].prompt
    front, _ = notefile.read(course.note_path("d1", 2))
    assert front["untaught"] is True and front["inputs"]
    skimmed.clear()
    assert generate.generate_deck(course, "d1")["skipped"] == [] and not skimmed


def test_image_only_content_is_sent_to_fallback_writer(course, skimmed):
    slides = course.slides("d1")
    slides[1] = {"index": 2, "title": "", "text": "", "speakerNotes": ""}
    write_json(course.deck_path("d1", "slides.json"), slides)
    image = course.deck_path("d1", "slides", "002.webp")
    image.parent.mkdir(parents=True)
    Image.new("RGB", (32, 18), "green").save(image)
    assert generate.generate_deck(course, "d1")["generated"] == [2]
    assert skimmed[0].images == skimmed[1].images == [image]


@pytest.mark.parametrize("partial", [False, True])
def test_old_transcript_skips_are_upgraded_even_with_an_unchanged_fingerprint(course, skimmed, partial):
    m = Gatherer(course, "d1").get(2)
    front = generate.meta(m, "skipped", m.inputs if partial else None)
    notefile.write(course.note_path("d1", 2), front, "這段在說明作業。")
    assert generate.generate_deck(course, "d1")["generated"] == [2]
    assert len(skimmed) == 2 and notefile.read(course.note_path("d1", 2))[0]["untaught"] is True


def test_review_preserves_fingerprint_then_changed_transcript_restores_timestamps(course, skimmed, monkeypatch):
    generate.generate_deck(course, "d1")
    original = notefile.read(course.note_path("d1", 2))[0]
    skimmed.clear()

    async def reviewer(call):
        skimmed.append(call)
        assert generate.UNTAUGHT_RULE in call.prompt and "a system call is like a door" not in call.prompt
        return '{"findings": []}'

    monkeypatch.setattr(claude, "complete", reviewer)
    assert review.review_deck(course, "d1")["reviewed"] == [2]
    front, _ = notefile.read(course.note_path("d1", 2))
    assert front["untaught"] is True and front["inputs"] == original["inputs"] and front["sources"] == []
    skimmed.clear()
    assert generate.generate_deck(course, "d1")["generated"] == [] and not skimmed
    transcript = course.transcript("v1")
    transcript["segments"][2]["text"] = "the teacher now explains the system call"
    write_json(course.video_path("v1", "transcript.json"), transcript)

    async def writer(call):
        skimmed.append(call)
        assert generate.LINKS_RULE in call.prompt
        return 'system call 透過 trap 進入 kernel [01:04](video:v1?t=64)。'

    monkeypatch.setattr(claude, "complete", writer)
    assert generate.generate_deck(course, "d1")["generated"] == [2] and len(skimmed) == 1
    front, body = notefile.read(course.note_path("d1", 2))
    assert "untaught" not in front and "inputs" not in front
    assert front["sources"] == ["v1@60-120"] and "video:" in body


def test_partial_fallback_is_refreshed_once_when_transcription_finishes(course, skimmed):
    full = course.video_path("v1", "transcript.json")
    saved = read_json(full)
    full.unlink()
    write_json(course.video_path("v1", "transcript.partial.json"), {"segments": saved["segments"][:3]})
    generate.generate_deck(course, "d1")
    front, _ = notefile.read(course.note_path("d1", 2))
    assert front["partial"] is True and front["untaught"] is True
    assert front["inputs"] == Gatherer(course, "d1").get(2).inputs
    skimmed.clear()
    assert generate.generate_deck(course, "d1")["generated"] == [] and not skimmed
    write_json(full, saved)
    assert generate.generate_deck(course, "d1")["generated"] == [2] and len(skimmed) == 2
    assert "partial" not in notefile.read(course.note_path("d1", 2))[0]


@pytest.mark.parametrize("status", ["edited", None])
def test_protected_old_skip_is_kept(course, skimmed, status):
    front = {"status": status} if status else {}
    notefile.write(course.note_path("d1", 2), front, "使用者的版本")
    assert generate.generate_deck(course, "d1")["generated"] == [] and not skimmed
    assert notefile.read(course.note_path("d1", 2))[1] == "使用者的版本"


def test_user_edit_during_fallback_is_kept(course, skimmed, monkeypatch):
    async def writer(call):
        if generate.NO_LINKS_RULE not in call.prompt:
            return "SKIP: 老師只翻過這頁。"
        notefile.write(course.note_path("d1", 2), {"status": "edited"}, "使用者剛改的")
        return BODY

    monkeypatch.setattr(claude, "complete", writer)
    assert generate.generate_deck(course, "d1")["kept"] == [2]
    assert notefile.read(course.note_path("d1", 2))[1] == "使用者剛改的"


def test_fallback_failure_leaves_existing_note_for_retry(course, skimmed, monkeypatch):
    path = course.note_path("d1", 2)
    notefile.write(path, {"status": "skipped"}, "之前的略過理由")
    saved = path.read_text()

    async def writer(call):
        if generate.NO_LINKS_RULE in call.prompt:
            raise RuntimeError("offline")
        return "SKIP: 只翻過這頁。"

    monkeypatch.setattr(claude, "complete", writer)
    with pytest.raises(RuntimeError, match="offline"):
        generate.generate_deck(course, "d1")
    assert path.read_text() == saved


def test_reviser_skip_also_falls_back_to_slides(course, skimmed, monkeypatch):
    m = Gatherer(course, "d1").get(2)
    notefile.write(course.note_path("d1", 2), generate.meta(m, "generated"), "總之，原稿。")

    async def reviewer(call):
        skimmed.append(call)
        if generate.UNTAUGHT_RULE in call.prompt:
            assert "a system call is like a door" not in call.prompt
            return BODY
        if "## 審稿意見" in call.prompt:
            return "SKIP: 逐字稿在講作業。"
        return '{"findings": []}'

    monkeypatch.setattr(claude, "complete", reviewer)
    assert review.review_deck(course, "d1")["reviewed"] == [2]
    assert len(skimmed) == 5
    front, body = notefile.read(course.note_path("d1", 2))
    assert front["untaught"] is True and front["sources"] == [] and front["inputs"] == m.inputs
    assert body.startswith(generate.UNTAUGHT_NOTICE) and "video:" not in body
    assert read_json(course.review_path("d1", 2))["unresolved"] == []
