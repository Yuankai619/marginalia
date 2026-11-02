import json

import pytest

from marginalia.llm import claude, codex
from marginalia.notes import generate, notefile, review, rules
from marginalia.notes.material import Gatherer
from marginalia.store import read_json


@pytest.fixture
def written(course, monkeypatch):
    async def writer(call):
        return "總之 kernel 管理硬體 [00:30](video:v1?t=30)。"

    monkeypatch.setattr(claude, "complete", writer)
    generate.generate_deck(course, "d1")
    return course


def fake_models(monkeypatch, revised="kernel 管理 CPU、記憶體和 I/O [00:30](video:v1?t=30)。"):
    seen = []

    async def fake(call):
        seen.append(call)
        if "## 審稿意見" in call.prompt:
            return revised
        if "負責正確性審稿" in call.prompt:
            finding = {"severity": "high", "quote": "kernel 管理硬體", "problem": "太籠統", "fix": "列出管理哪些硬體"}
            return "好的，結果如下：\n```json\n" + json.dumps({"findings": [finding]}, ensure_ascii=False) + "\n```"
        if "負責涵蓋度審稿" in call.prompt:
            return '{"findings": []}'
        return '{"findings": [{"severity": "weird", "quote": "", "problem": "開頭空泛", "fix": "刪掉"}]}'

    monkeypatch.setattr(claude, "complete", fake)
    return seen


def test_review_writes_findings_and_revises(written, monkeypatch):
    seen = fake_models(monkeypatch)
    out = review.review_deck(written, "d1")
    assert out == {"reviewed": [1, 2], "revised": [1, 2], "failed": {}}  # slide 3 is skipped: nothing to review

    rec = read_json(written.review_path("d1", 1))
    by = {f["reviewer"] for f in rec["findings"]}
    assert by == {"rules", "correctness", "style"}
    assert rec["findings"][0]["severity"] == "high"
    assert next(f for f in rec["findings"] if f["reviewer"] == "style")["severity"] == "medium"
    assert rec["revised"] is True and "errors" not in rec

    meta, body = notefile.read(written.note_path("d1", 1))
    assert meta["status"] == "reviewed" and body.startswith("kernel 管理 CPU")
    assert len(seen) == 2 * 4  # three reviewers + one revision per slide

    assert review.review_deck(written, "d1")["reviewed"] == []  # resume: already reviewed


def test_edited_note_gets_findings_but_is_not_rewritten(written, monkeypatch):
    fake_models(monkeypatch)
    path = written.note_path("d1", 1)
    meta, _ = notefile.read(path)
    notefile.write(path, {**meta, "status": "edited"}, "我的版本，總之")
    out = review.review_deck(written, "d1", slides=[1])
    assert out["reviewed"] == [1] and out["revised"] == []
    assert notefile.read(path)[1].strip() == "我的版本，總之"
    assert read_json(written.review_path("d1", 1))["findings"]


def test_one_reviewer_failing_is_recorded(written, monkeypatch):
    fake_models(monkeypatch)
    inner = claude.complete

    async def flaky(call):
        if "負責涵蓋度審稿" in call.prompt:
            raise RuntimeError("rate limited")
        return await inner(call)

    monkeypatch.setattr(claude, "complete", flaky)
    review.review_deck(written, "d1", slides=[2])
    assert read_json(written.review_path("d1", 2))["errors"] == {"coverage": "rate limited"}


def test_all_reviewers_failing_raises(written, monkeypatch):
    async def down(call):
        raise RuntimeError("offline")

    monkeypatch.setattr(claude, "complete", down)
    with pytest.raises(RuntimeError, match="審稿失敗"):
        review.review_deck(written, "d1", slides=[1])
    assert notefile.read(written.note_path("d1", 1))[0]["status"] == "generated"


def test_codex_second_opinion(written, monkeypatch, tmp_path):
    fake_models(monkeypatch)
    monkeypatch.setattr(codex, "available", lambda home: True)

    async def fake_codex(prompt, **kw):
        assert kw["codex_home"] == tmp_path and "正確性審稿" in prompt
        return '{"findings": [{"severity": "low", "quote": "x", "problem": "codex 意見", "fix": "y"}]}'

    monkeypatch.setattr(codex, "complete", fake_codex)
    review.review_deck(written, "d1", slides=[1], codex_home=tmp_path)
    assert any(f["reviewer"] == "codex-correctness" for f in read_json(written.review_path("d1", 1))["findings"])


def test_parse_findings():
    assert review.parse_findings('{"findings": []}', "x") == []
    with pytest.raises(ValueError):
        review.parse_findings("no json here", "x")
    got = review.parse_findings('{"findings": [{"problem": "p", "quote": 3}, "junk", {"severity": "low"}]}', "x")
    assert got == [{"reviewer": "x", "severity": "medium", "quote": "3", "problem": "p", "fix": ""}]


def test_rules_check(course):
    m = Gatherer(course, "d1").get(2)
    body = (
        "總之，作業系統扮演著重要角色 ✅。\n\n**a** **b** **c** **d**\n\n## 什麼是 kernel？\n\n"
        "內存很大。進入 kernel [01:04](video:v1?t=64)、[00:10](video:v1?t=99)、[01:00](video:v1?t=500)、"
        "[00:01](video:v9?t=64)、[x](video:v1?t=abc)"
    )
    problems = [f["problem"] for f in rules.check(body, m)]
    joined = "\n".join(problems)
    for expected in ("套話「總之」", "套話「扮演著」", "emoji", "粗體 4 處", "問句當標題", "大陸用語「內存」"):
        assert expected in joined
    assert "標籤 00:10 和 t=99（01:39）不一致。" in problems
    assert "08:20 對不到這頁逐字稿任何一句的開頭。" in problems
    assert "影片 v9 不是這頁出現的影片。" in problems
    assert "時間點 t=abc 不是秒數。" in problems
    assert rules.check("[x](video:v1?t=1e999)", m)[0]["problem"] == "時間點 t=1e999 不是秒數。"
    assert rules.check("kernel 透過 system call 提供服務 [01:04](video:v1?t=64)。", m) == []
    assert rules.check("[01:33](video:v1?t=93)", m) == []  # within LINE_SLACK of the t=90 line


def test_links_without_transcript_use_the_on_screen_range(course):
    (course.video_dir("v1") / "transcript.json").unlink()
    m = Gatherer(course, "d1").get(2)
    assert rules.check("[01:20](video:v1?t=80)", m) == []
    assert rules.check("[05:00](video:v1?t=300)", m)[0]["problem"] == "05:00 不在這頁出現在影片上的時間範圍內。"


def test_normalize_links():
    assert rules.normalize_links("[x](video:v1?t=nan)") == "[x](video:v1?t=nan)"
    assert rules.normalize_links("[0:00](video:v1?t=3725.4)") == "[1:02:05](video:v1?t=3725)"
    assert rules.normalize_links("[a](video:v1?t=x)") == "[a](video:v1?t=x)"
