"""Generate tiny courses for the real static-export browser regression (run via server/uv)."""

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image

from marginalia import config
from marginalia.store import Course, write_json, write_text

parser = argparse.ArgumentParser()
parser.add_argument("courses", type=Path)
args = parser.parse_args()
config.COURSES_DIR = args.courses
image = BytesIO()
Image.new("RGB", (320, 180), "#bdd5ce").save(image, "WEBP")
for course_id in ("fixture", "text-only"):
    course = Course(course_id)
    course.save_info({"title": "靜態驗證課程", "hiddenDecks": ["hidden"],
                      "videoUrls": {"video-b": "https://example.com/public-videos/ascii.mp4",
                                    "課堂一": "https://example.com/public-videos/chinese.mp4"}
                      if course_id == "fixture" else {}})
    course.save_manifest({"decks": [{"id": d, "title": "測試簡報", "source": f"materials/{d}.pdf"}
                                    for d in ("deck", "hidden")],
                          "videos": [{"id": v, "title": "測試錄影", "duration": 60, "source": f"materials/{v}.mp4"}
                                     for v in ("video-b", "課堂一")]})
    write_json(course.deck_path("deck", "slides.json"), [{"index": i, "title": f"測試投影片 {i}"} for i in (1, 2)])
    for i in (1, 2):
        for folder in ("slides", "thumbs"):
            path = course.deck_path("deck", folder, f"{i:03d}.webp")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(image.getvalue())
    write_text(course.note_path("deck", 1), '''---
status: reviewed
updatedAt: 2026-11-03T00:00:00Z
---
# 合成筆記

> [!IMPORTANT]
> ==資料契約驗證==

[00:12](video:video-b?t=12) [中文影片](video:課堂一?t=12) [編碼影片](video:%E8%AA%B2%E5%A0%82%E4%B8%80?t=24)

```mermaid
flowchart LR
 A["第一步"] --> B["第二步"]
```

![架構](assets/架構圖.svg)
''')
    write_text(course.note_path("deck", 2), "第二頁原始筆記")
    write_text(course.path("notes", "deck", "assets", "架構圖.svg"),
               '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="green"/></svg>')
    write_json(course.path("generated", "alignment.json"), {"segments": [
        {"video": "video-b", "deck": "deck", "slide": 1, "start": 12, "end": 24}]})
    for v in ("video-b", "課堂一"):
        write_json(course.video_path(v, "transcript.json"), {"segments": [{"start": 12, "end": 24, "text": "合成逐字稿"}]})
    if course_id == "fixture":
        # Exam prep: handout + quiz are exported; uploads and attempts must not be.
        exam = Path(course.path("exams", "midterm"))
        write_json(exam / "exam.json", {"title": "期中考", "scope": {"decks": ["deck"]}})
        write_text(exam / "handout" / "001.md", "---\nsection: 1\ntitle: 合成講義\nstatus: generated\n---\n\n"
                   "> [!IMPORTANT]\n> ==講義重點==\n\n![投影片](slide:deck/1)\n\n![隱藏](slide:hidden/1)\n")
        write_json(exam / "quiz.json", {"version": 1, "hash": "h1", "questions": [
            {"id": "q1", "type": "choice", "origin": "past", "pastRef": "secret-paper.png", "prompt": "合成選擇題",
             "options": [{"id": "A", "text": "錯"}, {"id": "B", "text": "對"}], "answer": ["B"], "points": 2,
             "solution": "合成詳解"},
            {"id": "q2", "type": "short", "origin": "new", "prompt": "合成簡答題", "points": 4, "solution": "合成參考答案",
             "rubric": [{"point": "合成要點", "points": 4}]}]})
        write_text(exam / "uploads" / "secret-paper.md", "不可匯出的考古題")
        write_json(exam / "attempts" / ("a" * 32 + ".json"), {"id": "a" * 32})
print(f"Generated static fixtures in {args.courses}")
