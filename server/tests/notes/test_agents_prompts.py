import pytest

from marginalia.agents import prompts
from marginalia.notes import notefile
from marginalia.store import write_json


def test_qa_prompt_has_outline_slide_and_note(course):
    notefile.write(course.note_path("d1", 2), {"slide": 2, "status": "generated"}, "system call 筆記內容")
    s = prompts.build_system(course, "qa", "d1", 2)
    assert "## 模式：問答" in s
    assert "- 第 3 頁：Backup Slide" in s and "User mode -> kernel mode" in s  # whole-course outline
    assert "generated/decks/d1/slides/002.webp" in s
    assert "[v1 t=64 01:04]" in s
    assert "system call 筆記內容" in s
    assert "筆記寫作規範" not in s


def test_course_id_string_and_no_slide(course):
    s = prompts.build_system("demo", "interview")
    assert "## 模式：口試" in s and "一次只問一題" in s
    assert "學生目前在看的投影片" not in s


def test_review_mode_includes_style_and_previous_findings(course):
    write_json(course.review_path("d1", 1), {"findings": [{"severity": "high", "problem": "時間點錯", "quote": "q"}]})
    s = prompts.build_system(course, "review", "d1", 1)
    assert "筆記寫作規範" in s and "AI 味" in s
    assert "[high] 時間點錯（q）" in s
    assert "（還沒有筆記）" in s


def test_selection_and_region(course):
    s = prompts.build_system(
        course, "qa", "d1", 1, selection={"text": "kernel mode\n是什麼", "source": "note"}, region={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.25}
    )
    assert "學生選取的文字（來自筆記）\n\n> kernel mode\n> 是什麼" in s
    assert "水平 10%–40%、垂直 20%–45%" in s


def test_outline_falls_back_to_titles(course):
    full = prompts.course_outline(course, "d1")
    other = {"id": "d2", "title": "L2", "source": "materials/d2.pptx", "slideCount": 1}
    man = course.manifest()
    man["decks"].append(other)
    course.save_manifest(man)
    write_json(course.deck_dir("d2") / "slides.json", [{"index": 1, "title": "Paging", "text": "Paging\n" + "x" * 500}])
    short = prompts.course_outline(course, "d1", limit=len(full) + 100)
    assert "Paging" in short and "x" * 50 not in short and "User mode -> kernel mode" in short


def test_hidden_decks_left_out(course):
    write_json(course.dir / "course.json", {"title": "Demo", "hiddenDecks": ["d1"]})
    assert "L1 Demo" not in prompts.course_outline(course)
    assert "L1 Demo" in prompts.course_outline(course, "d1")


def test_bad_input(course):
    with pytest.raises(ValueError):
        prompts.build_system(course, "chat")
    with pytest.raises(KeyError):
        prompts.build_system(course, "qa", "nope", 1)
    with pytest.raises(IndexError):
        prompts.build_system(course, "qa", "d1", 9)
