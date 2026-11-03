import json

import pytest

from marginalia.llm import claude, codex
from marginalia.notes import generate, notefile, review, rules
from marginalia.notes.material import Gatherer
from marginalia.store import read_json


@pytest.fixture
def written(course, monkeypatch):
    async def writer(call):
        if "第 3 頁「Backup Slide」" in call.prompt:
            return "SKIP: 這頁只有標題。"
        return "總之 kernel 管理硬體 [00:30](video:v1?t=30)。"

    monkeypatch.setattr(claude, "complete", writer)
    generate.generate_deck(course, "d1")
    return course


def fake_models(monkeypatch, revised="kernel 管理 CPU、記憶體和 I/O。"):
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
    assert out["reviewed"] == [1, 2] and out["revised"] == [1, 2]  # slide 3 is skipped: nothing to review

    rec = read_json(written.review_path("d1", 1))
    by = {f["reviewer"] for f in rec["findings"]}
    assert by == {"rules", "correctness", "style"}
    assert rec["findings"][0]["severity"] == "high"
    assert next(f for f in rec["findings"] if f["reviewer"] == "style")["severity"] == "medium"
    assert rec["revised"] is True and "errors" not in rec and rec["unresolved"] == []

    meta, body = notefile.read(written.note_path("d1", 1))
    assert meta["status"] == "reviewed" and body.startswith("kernel 管理 CPU")
    assert rec["noteHash"] == notefile.digest(body) != rec["reviewedHash"]
    assert len(seen) == 2 * 4  # three reviewers + one revision per slide

    assert review.review_deck(written, "d1")["reviewed"] == []  # resume: already reviewed


def test_edited_note_gets_findings_but_is_not_rewritten(written, monkeypatch):
    fake_models(monkeypatch)
    path = written.note_path("d1", 1)
    meta, _ = notefile.read(path)
    notefile.write(path, {**meta, "status": "edited"}, "我的版本，總之")
    out = review.review_deck(written, "d1", slides=[1])
    assert out["kept"] == [1] and out["revised"] == []
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
    with pytest.raises(RuntimeError, match="第 1、2 頁審稿失敗：第 1 頁 coverage 審稿失敗：rate limited"):
        review.review_deck(written, "d1")
    assert read_json(written.review_path("d1", 2))["errors"] == {"coverage": "rate limited"}
    assert notefile.read(written.note_path("d1", 2))[0]["status"] == "generated"  # not passed off as reviewed

    monkeypatch.setattr(claude, "complete", inner)  # the outage is over: a plain rerun retries those slides
    assert review.review_deck(written, "d1")["reviewed"] == [1, 2]


def test_all_reviewers_failing_raises(written, monkeypatch):
    async def down(call):
        raise RuntimeError("offline")

    monkeypatch.setattr(claude, "complete", down)
    with pytest.raises(RuntimeError, match="審稿失敗"):
        review.review_deck(written, "d1", slides=[1])
    assert notefile.read(written.note_path("d1", 1))[0]["status"] == "generated"


def test_revision_that_breaks_the_rules_is_not_marked_reviewed(written, monkeypatch):
    seen = fake_models(monkeypatch, revised="錯誤連結 [00:01](video:v9?t=1)")
    out = review.review_deck(written, "d1", slides=[1])
    assert out["unresolved"] == [1] and out["reviewed"] == []
    assert sum("## 審稿意見" in c.prompt for c in seen) == review.MAX_REVISIONS  # bounded retries
    meta, body = notefile.read(written.note_path("d1", 1))
    assert meta["status"] == "generated" and "v9" in body
    rec = read_json(written.review_path("d1", 1))
    assert rec["unresolved"][0]["problem"] == "影片 v9 不是這頁出現的影片。"


def test_second_revision_round_fixes_rule_problems(written, monkeypatch):
    replies = iter(["錯誤連結 [00:01](video:v9?t=1)", "kernel 管理 CPU [00:30](video:v1?t=30)。"])
    fake_models(monkeypatch)
    inner = claude.complete

    async def fake(call):
        return next(replies) if "## 審稿意見" in call.prompt else await inner(call)

    monkeypatch.setattr(claude, "complete", fake)
    assert review.review_deck(written, "d1", slides=[1])["reviewed"] == [1]
    assert notefile.read(written.note_path("d1", 1))[0]["status"] == "reviewed"


def test_empty_revision_is_unresolved(written, monkeypatch):
    fake_models(monkeypatch, revised="   ")
    assert review.review_deck(written, "d1", slides=[1])["unresolved"] == [1]
    meta, body = notefile.read(written.note_path("d1", 1))
    assert meta["status"] == "generated" and body.startswith("總之")


def test_note_changed_during_review_is_left_alone(written, monkeypatch):
    fake_models(monkeypatch)
    inner = claude.complete
    path = written.note_path("d1", 1)

    async def racing(call):
        if "## 審稿意見" in call.prompt:  # another job rewrites the note while the reviser runs
            notefile.write(path, {"slide": 1, "status": "generated"}, "另一個工作的版本")
        return await inner(call)

    monkeypatch.setattr(claude, "complete", racing)
    out = review.review_deck(written, "d1", slides=[1])
    assert out["conflict"] == [1] and out["revised"] == []
    assert notefile.read(path)[1] == "另一個工作的版本"
    assert read_json(written.review_path("d1", 1)) is None  # findings about a stale text are not stored


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


TOP = "> [!IMPORTANT]\n> kernel 透過 system call 提供服務 [01:04](video:v1?t=64)。\n\n"


def problems(body: str, m) -> list[str]:
    return [f["problem"] for f in rules.check(body, m)]


def test_rules_check(course):
    m = Gatherer(course, "d1").get(2)
    body = (
        "總之，作業系統扮演著重要角色 ✅。\n\n## 什麼是 kernel？\n\n"
        "內存很大。進入 kernel [01:04](video:v1?t=64)、[00:10](video:v1?t=99)、[01:00](video:v1?t=500)、"
        "[00:01](video:v9?t=64)、[x](video:v1?t=abc)"
    )
    got = problems(body, m)
    joined = "\n".join(got)
    for expected in ("套話「總之」", "套話「扮演著」", "emoji", "問句當標題", "大陸用語「內存」", "開頭不是 > [!IMPORTANT]"):
        assert expected in joined
    assert "標籤 00:10 和 t=99（01:39）不一致。" in got
    assert "08:20 對不到這頁逐字稿任何一句的開頭。" in got
    assert "影片 v9 不是這頁出現的影片。" in got
    assert "時間點 t=abc 不是秒數。" in got
    assert problems(TOP + "[x](video:v1?t=1e999)", m) == ["時間點 t=1e999 不是秒數。"]
    assert rules.check(TOP, m) == []
    assert rules.check(TOP + "[01:33](video:v1?t=93)", m) == []  # within LINE_SLACK of the t=90 line


def test_v2_marks(course):
    m = Gatherer(course, "d1").get(2)
    terms = " ".join(f"**term{i}**" for i in range(12))  # many bold terms are fine now
    assert rules.check(TOP + terms + " ==要記住的一句== 和 ==另一句==", m) == []
    got = problems(TOP + "**這一整句都被加粗了。** ==沒關好 > [!NOTICE] x", m)
    assert got == ["整句或整段粗體。", "==highlight== 沒有配對。"]
    assert "提示框類型 [!NOTICE] 不合法。" in problems(TOP + "> [!NOTICE]\n> x", m)
    assert "highlight 7 處，超過 5 處。" in problems(TOP + " ".join(f"==h{i}==" for i in range(7)), m)


def test_prose_checks_skip_code(course):
    m = Gatherer(course, "d1").get(2)
    code = "```mermaid\nflowchart TD\n  A[\"總之\"] ==> B[\"內存\"]\n```\n\n`==` 和 `**總之。**`"
    assert rules.check(TOP + code, m) == []


def test_mermaid_checks(course):
    m = Gatherer(course, "d1").get(2)

    def mermaid(src: str) -> list[str]:
        return problems(TOP + f"```mermaid\n{src}\n```", m)

    assert mermaid('flowchart LR\n  A["CPU (中央)"] -->|"trap"| B{"kernel?"}') == []
    assert mermaid("sequenceDiagram\n  participant K as Kernel\n  K->>K: run") == []
    assert mermaid("pie\n  a: 1") == ["mermaid 圖類型「pie」不支援，圖會壞掉。"]
    assert mermaid('flowchart LR\n  A["x"] --> B["y"') == ["mermaid 圖的括號沒有配對，圖會壞掉。"]
    assert mermaid("flowchart LR\n  A[CPU (中央)] --> B") == ["節點文字裡有括號卻沒加引號，mermaid 會解析失敗。"]
    assert problems(TOP + "```mermaid\nflowchart LR\n  A --> B", m) == ["程式碼區塊（```）沒有關閉。"]


def test_image_checks(course, tmp_path):
    m = Gatherer(course, "d1").get(2)
    m.assets.mkdir(parents=True)
    (m.assets / "arch.svg").write_text("<svg/>")
    missing = "圖片 assets/missing.png 不存在，或不是 assets/ 裡的一般檔案。"
    assert rules.check(TOP + "![架構](assets/arch.svg)", m) == []
    assert problems(TOP + "![x](assets/missing.png)", m) == [missing]
    for bad in ("../secret.png", "/etc/passwd", "assets/../../x.svg", "https://example.com/a.png", "assets/a.gif"):
        assert problems(TOP + f"![x]({bad})", m) == ["圖片路徑必須是 assets/<檔名>.png|jpg|webp|svg。"], bad
    # code is not an image; reference-style and HTML images are refused rather than half-checked
    assert rules.check(TOP + "範例：`![圖](assets/not-created.svg)`\n\n```\n![圖](assets/x.svg)\n```", m) == []
    assert problems(TOP + "![圖][arch]\n\n[arch]: ../../outside.svg", m) == ["不支援參照式圖片。"]
    assert problems(TOP + '<img src="assets/arch.svg">', m) == ["不允許用 HTML 放圖片。"]
    # a link inside assets/ pointing outside is not an asset
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg/>")
    (m.assets / "link.svg").symlink_to(outside)
    assert problems(TOP + "![x](assets/link.svg)", m) == ["圖片 assets/link.svg 不存在，或不是 assets/ 裡的一般檔案。"]


def test_assets_folder_that_is_a_link_is_refused(course, tmp_path):
    m = Gatherer(course, "d1").get(2)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.svg").write_text("<svg/>")
    m.assets.parent.mkdir(parents=True)
    m.assets.symlink_to(elsewhere)
    assert problems(TOP + "![x](assets/a.svg)", m) == ["圖片 assets/a.svg 不存在，或不是 assets/ 裡的一般檔案。"]


def test_mermaid_comments_are_not_syntax(course):
    m = Gatherer(course, "d1").get(2)
    src = 'flowchart TD\n%% [這是註解，不是節點 (\n  A["CPU"] --> B["RAM"]'
    assert rules.check(TOP + f"```mermaid\n{src}\n```", m) == []


def test_rule_findings_are_deduplicated_and_bounded(course):
    m = Gatherer(course, "d1").get(2)
    found = rules.check(TOP + "總之。" * 10_000, m)
    assert len(found) <= rules.MAX_RULE_FINDINGS


def test_long_note_is_not_rewritten(written, monkeypatch):
    seen = fake_models(monkeypatch)
    path = written.note_path("d1", 1)
    meta, _ = notefile.read(path)
    body = "總之開頭。\n\n" + "內容。" * 8_000 + "\n\nTAIL_MUST_SURVIVE"
    notefile.write(path, meta, body)
    out = review.review_deck(written, "d1", slides=[1])
    assert out["too_long"] == [1] and not seen  # no model saw a truncated note
    meta2, body2 = notefile.read(path)
    assert body2.endswith("TAIL_MUST_SURVIVE") and meta2["status"] == "generated"
    assert "超過自動審稿上限" in read_json(written.review_path("d1", 1))["findings"][-1]["problem"]


def test_revision_prompt_stays_bounded(course):
    m = Gatherer(course, "d1").get(2)
    findings = rules.check("總之。" * 10_000, m) + [
        {"reviewer": "style", "severity": "medium", "quote": "q" * 600, "problem": "p" * 600, "fix": "f" * 600}
    ] * 500
    prompt = review.revise_prompt(m, "總之。" * 5_000, findings)
    assert len(prompt) < 60_000 and "這次先不處理" in prompt


def test_links_without_transcript_use_the_on_screen_range(course):
    (course.video_dir("v1") / "transcript.json").unlink()
    m = Gatherer(course, "d1").get(2)
    top = "> [!IMPORTANT]\n> x\n\n"
    assert rules.check(top + "[01:20](video:v1?t=80)", m) == []
    assert rules.check(top + "[05:00](video:v1?t=300)", m)[0]["problem"] == "05:00 不在這頁出現在影片上的時間範圍內。"


def test_normalize_links():
    assert rules.normalize_links("[x](video:v1?t=60.4)") == "[01:00](video:v1?t=60)"
    assert rules.normalize_links("[x](video:v1?t=60.6)") == "[01:01](video:v1?t=61)"
    assert rules.normalize_links("[x](video:v1?t=59.8)") == "[01:00](video:v1?t=60)"
    assert rules.normalize_links("[x](video:v1?t=3599.8)") == "[1:00:00](video:v1?t=3600)"
    assert rules.normalize_links("[x](video:v1?t=nan)") == "[x](video:v1?t=nan)"
    assert rules.normalize_links("[0:00](video:v1?t=3725.4)") == "[1:02:05](video:v1?t=3725)"
    assert rules.normalize_links("[a](video:v1?t=x)") == "[a](video:v1?t=x)"


def test_untaught_review_uses_slides_and_preserves_marker(course, monkeypatch, tmp_path):
    front = {"status": "generated", "untaught": True, "inputs": "original-inputs", "sources": []}
    path = course.note_path("d1", 3)
    notefile.write(path, front, "老師說 kernel 管理硬體 [00:30](video:v1?t=30)。")
    seen = []

    async def fake(call):
        seen.append(call)
        assert generate.UNTAUGHT_RULE in call.prompt
        assert "quote 填逐字稿" not in call.prompt
        if "## 審稿意見" in call.prompt:
            return "> [!IMPORTANT]\n> ==kernel 管理硬體==。 [00:30](video:v1?t=30)"
        return '{"findings": []}'

    async def fake_codex(prompt, **kwargs):
        assert review.UNTAUGHT_REVIEWERS["correctness"] in prompt
        return '{"findings": []}'

    monkeypatch.setattr(claude, "complete", fake)
    monkeypatch.setattr(codex, "available", lambda home: True)
    monkeypatch.setattr(codex, "complete", fake_codex)
    assert review.review_deck(course, "d1", codex_home=tmp_path)["reviewed"] == [3]
    assert len(seen) == 4
    for task in review.UNTAUGHT_REVIEWERS.values():
        assert any(task in call.prompt for call in seen)
    new_front, body = notefile.read(path)
    assert new_front["status"] == "reviewed" and new_front["untaught"] is True
    assert new_front["inputs"] == "original-inputs" and new_front["sources"] == []
    assert body.startswith(generate.UNTAUGHT_NOTICE) and "video:" not in body
    record = read_json(course.review_path("d1", 3))
    assert any(f["problem"] == "課堂未講解頁不能有影片時間點連結。" for f in record["findings"])
    assert record["unresolved"] == []


def test_untaught_review_after_alignment_does_not_consume_new_transcript(course, monkeypatch):
    notefile.write(course.note_path("d1", 2), {"status": "generated", "untaught": True, "inputs": "old"}, generate.UNTAUGHT_NOTICE)

    async def fake(call):
        assert generate.UNTAUGHT_RULE in call.prompt
        assert "a system call is like a door" not in call.prompt
        return '{"findings": []}'

    monkeypatch.setattr(claude, "complete", fake)
    review.review_deck(course, "d1", slides=[2])
    front, _ = notefile.read(course.note_path("d1", 2))
    assert front["untaught"] is True and front["inputs"] == "old" and front["sources"] == []
