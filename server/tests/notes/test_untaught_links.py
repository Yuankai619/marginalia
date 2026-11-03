"""Synthetic model replies exercise the full write/revise/export boundary, with no model calls."""

import json

import pytest

from marginalia.export import export_courses
from marginalia.llm import claude
from marginalia.notes import generate, notefile, review, rules
from marginalia.notes.material import Gatherer
from marginalia.notes.video_links import has_video_links, strip_video_links
from marginalia.store import read_json

LINKS = [
    '[00:12](video:v1?t=12 "課堂來源")',
    "[00:12](video:v1?t=12 '課堂來源')",
    '[00:12](video:v1?t=12 (課堂來源))',
    '[00:12](<video:v1?t=12> "課堂來源")',
    '[00:12][source]\n\n[source]: video:v1?t=12 "課堂來源"',
    '[00:12][ SOURCE ]\n\n[source]:\n  <video:v1?t=12>',
    '[source][]\n\n[source]: video:v1?t=12',
    '[source]\n\n[source]: video:v1?t=12',
    '<a href="video:v1?t=12" title="課堂來源"><strong>00:12</strong></a>',
    "<A title='課堂 > 來源' HREF=video:v1?t=12>00:12</A>",
    '<a href="v&#105;deo&#58;v1?t=12">00:12</a>',
    '[00:12](v&#105;deo&colon;v1?t=12 "課堂來源")',
    r'[00:12](video\:v1?t=12 "課堂來源")',
    '<video:v1?t=12>',
]
TOP = '> [!IMPORTANT]\n> ==依投影片整理的重點==。\n\n'


def exported_note(course, tmp_path_factory):
    out = tmp_path_factory.mktemp("untaught-export") / "snapshot"
    export_courses(out, [course.id])
    return json.loads((out / "data/demo/decks/d1.json").read_text())["notes"].get("3")


@pytest.mark.parametrize("link", LINKS)
@pytest.mark.parametrize("stage", ["generate", "revise"])
def test_model_video_links_are_filtered_before_write_and_export(course, monkeypatch, tmp_path_factory, link, stage):
    async def fake(call):
        if stage == "generate" or "## 審稿意見" in call.prompt:
            return TOP + link
        return '{"findings": []}'

    monkeypatch.setattr(claude, "complete", fake)
    path = course.note_path("d1", 3)
    if stage == "generate":
        assert generate.generate_deck(course, "d1", slides=[3])["generated"] == [3]
    else:
        m = Gatherer(course, "d1").get(3)
        notefile.write(path, generate.meta(m, "generated"), generate.UNTAUGHT_NOTICE + "\n\n總之，內容。")
        assert review.review_deck(course, "d1", slides=[3])["reviewed"] == [3]
        assert read_json(course.review_path("d1", 3))["unresolved"] == []
    front, body = notefile.read(path)
    assert front["untaught"] is True and front["sources"] == []
    assert body.startswith(generate.UNTAUGHT_NOTICE)
    assert "依投影片整理的重點" in body
    assert "video:" not in body and not has_video_links(body)
    assert rules.check_links(body, Gatherer(course, "d1").get(3)) == []
    exported = exported_note(course, tmp_path_factory)
    assert exported["markdown"].strip() == body
    assert not has_video_links(exported["markdown"])


@pytest.mark.parametrize("link", LINKS)
def test_rules_detect_video_links_even_when_syntax_is_not_canonical(course, link):
    found = rules.check_links(TOP + link, Gatherer(course, "d1").get(3))
    assert len(found) == 1 and found[0]["severity"] == "high"
    assert found[0]["problem"] == "課堂未講解頁不能有影片時間點連結。"


@pytest.mark.parametrize("stage", ["generate", "revise", "skip", "revise-skip"])
def test_filter_residue_stays_generated_with_finding_and_is_not_exported(course, monkeypatch, tmp_path_factory, stage):
    # Simulate an unfamiliar syntax escaping the filter; the independent postcondition must still catch it.
    monkeypatch.setattr(generate, "strip_video_links", lambda body: body)

    async def fake(call):
        if stage == "skip" or (stage == "revise-skip" and "## 審稿意見" in call.prompt):
            return 'SKIP: 空白頁 <a href="video:v1?t=12">00:12</a>'
        if stage == "generate" or "## 審稿意見" in call.prompt:
            return TOP + LINKS[0]
        return '{"findings": []}'

    monkeypatch.setattr(claude, "complete", fake)
    path = course.note_path("d1", 3)
    if stage.startswith("revise"):
        m = Gatherer(course, "d1").get(3)
        notefile.write(path, generate.meta(m, "generated"), generate.UNTAUGHT_NOTICE + "\n\n總之，內容。")
        assert review.review_deck(course, "d1", slides=[3])["unresolved"] == [3]
    else:
        assert generate.generate_deck(course, "d1", slides=[3])["generated"] == [3]
    front, body = notefile.read(path)
    assert front["status"] == "generated"
    assert body.startswith(generate.UNTAUGHT_NOTICE)
    record = read_json(course.review_path("d1", 3))
    assert record["unresolved"][0]["problem"] == "課堂未講解頁不能有影片時間點連結。"
    assert record["unresolved"][0]["severity"] == "high"
    assert exported_note(course, tmp_path_factory) is None


def test_non_video_content_is_preserved():
    text = TOP + '[資料](https://example.com "來源")\n\n[ref]\n\n[ref]: https://example.com\n\n<a href="https://example.com">資料</a>\n\n`CPU`'
    assert strip_video_links(text) == text


def test_taught_model_reply_keeps_video_links(course, monkeypatch):
    async def fake(call):
        return TOP + LINKS[0]

    monkeypatch.setattr(claude, "complete", fake)
    generate.generate_deck(course, "d1", slides=[1])
    assert LINKS[0] in notefile.read(course.note_path("d1", 1))[1]


@pytest.mark.parametrize("status", ["edited", None])
def test_export_preserves_user_authored_content(course, tmp_path_factory, status):
    front = {"untaught": True}
    if status:
        front["status"] = status
    body = TOP + LINKS[0]
    notefile.write(course.note_path("d1", 3), front, body)
    assert exported_note(course, tmp_path_factory)["markdown"].strip() == body
