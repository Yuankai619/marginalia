"""Generated fixtures only; no real course content."""

import json
from io import BytesIO

import pytest
from PIL import Image

from marginalia import config
from marginalia.export import export_courses
from marginalia.store import Course, write_json, write_text


@pytest.fixture
def course(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path / "courses")
    value = Course("fixture")
    value.materials.mkdir(parents=True)
    return value


@pytest.fixture
def public_course(course):
    course.save_info(
        {
            "title": "測試課程",
            "hiddenDecks": ["hidden"],
            "videoUrls": {"recording": "https://example.com/lecture.mp4"},
            "owner": "/home/private-user",
            "internalIp": "100.90.1.2",
        }
    )
    course.save_manifest(
        {
            "decks": [
                {
                    "id": d,
                    "title": d,
                    "source": f"materials/{d}.pdf",
                    "author": "private-user",
                }
                for d in ("deck", "hidden")
            ],
            "videos": [
                {
                    "id": "recording",
                    "title": "錄影",
                    "duration": 60,
                    "source": "materials/secret.mp4",
                    "localPath": "/home/private-user",
                }
            ],
        }
    )
    image = BytesIO()
    Image.new("RGB", (16, 9), "green").save(image, "WEBP")
    for deck in ("deck", "hidden"):
        write_json(
            course.deck_path(deck, "slides.json"),
            [
                {
                    "index": i,
                    "title": f"第 {i} 頁",
                    "text": "投影片文字",
                    "speakerNotes": "講者備註",
                    "internalPath": "/home/private-user",
                }
                for i in range(1, 5)
            ],
        )
        for i in range(1, 5):
            for folder in ("slides", "thumbs"):
                path = course.deck_path(deck, folder, f"{i:03d}.webp")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(image.getvalue())
    write_text(
        course.note_path("deck", 1),
        "---\nstatus: reviewed\ninputs: secret-fingerprint\n---\n"
        "# 合成筆記\n\n> [!IMPORTANT]\n> ==資料契約驗證== [00:12](video:recording?t=12)\n\n"
        '```mermaid\nflowchart LR\n A["第一步"] --> B["第二步"]\n```\n\n'
        "![架構](assets/架構圖.svg)",
    )
    write_text(
        course.note_path("deck", 2),
        "---\nstatus: generated\npartial: true\n---\n未完成草稿",
    )
    write_text(course.note_path("deck", 3), "---\nstatus: draft\n---\n內部草稿")
    write_text(course.note_path("deck", 4), "手寫筆記")
    write_text(
        course.path("notes", "deck", "assets", "架構圖.svg"),
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
    )
    write_text(course.path("notes", "deck", "assets", "unused.svg"), "未引用私密圖片")
    write_json(course.review_path("deck", 1), {"raw": "內部審稿資料"})
    write_json(
        course.video_path("recording", "transcript.json"),
        {
            "segments": [
                {
                    "start": 12,
                    "end": 24,
                    "text": "合成逐字稿",
                    "private": "/home/private-user",
                }
            ],
            "sourceFingerprint": {"source": "materials/secret.mp4", "size": 100},
        },
    )
    write_json(
        course.video_path("recording", "transcript.partial.json"),
        {"segments": [{"text": "草稿"}]},
    )
    write_json(
        course.path("generated", "alignment.json"),
        {
            "videos": {"recording": {"path": "/home/private-user"}},
            "segments": [
                {
                    "video": "recording",
                    "deck": d,
                    "slide": 1,
                    "start": 12,
                    "end": 24,
                    "localPath": "/home/private-user",
                }
                for d in ("deck", "hidden")
            ],
        },
    )
    write_text(course.path("materials", "secret.mp4"), "RAW VIDEO")
    return course


def test_public_snapshot(public_course, tmp_path):
    out = tmp_path / "output"
    assert export_courses(out) == 1
    files = [str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()]
    assert all(
        "hidden" not in p and "materials" not in p and "reviews" not in p for p in files
    )
    assert not any(p.endswith((".mp4", ".pdf", ".md")) for p in files)
    assert all((out / p).stat().st_mode & 0o777 == 0o644 for p in files)
    contents = "\n".join(p.read_text() for p in out.rglob("*.json"))
    for private in (
        "/home/",
        "private-user",
        "100.90.1.2",
        "sourceFingerprint",
        "未完成草稿",
        "內部草稿",
        "raw",
        "localPath",
    ):
        assert private not in contents
    deck = json.loads((out / "data/fixture/decks/deck.json").read_text())
    assert set(deck["notes"]) == {"1", "4"}
    assert deck["notes"]["1"]["meta"] == {"status": "reviewed"}
    assert deck["notes"]["4"]["meta"]["status"] == "edited"
    assert "review" not in deck["notes"]["1"]
    assert deck["slides"][0]["ranges"] == [
        {"video": "recording", "start": 12, "end": 24}
    ]
    assert deck["slides"][1]["note"] is None
    assert (out / "files/fixture/notes/deck/assets/架構圖.svg").is_file()
    assert not (out / "files/fixture/notes/deck/assets/unused.svg").exists()
    assert json.loads((out / "data/courses.json").read_text())[0]["deckCount"] == 1
    assert (
        len(json.loads((out / "data/fixture/alignment.json").read_text())["segments"])
        == 1
    )


def test_existing_output_rejected(course, tmp_path):
    out = tmp_path / "empty"
    assert export_courses(out, [course.id]) == 1
    with pytest.raises(ValueError, match="已有"):
        export_courses(out)


def test_untaught_notes_are_exported_with_disclosure(public_course, tmp_path):
    from marginalia.notes.generate import UNTAUGHT_NOTICE

    body = f"{UNTAUGHT_NOTICE}\n\n==依投影片整理的重點==。"
    write_text(
        public_course.note_path("deck", 3),
        f"---\nstatus: generated\nuntaught: true\ninputs: private-fingerprint\nsources: []\n---\n{body}",
    )
    out = tmp_path / "untaught-export"
    export_courses(out)
    deck = json.loads((out / "data/fixture/decks/deck.json").read_text())
    assert deck["notes"]["3"]["markdown"].strip() == body
    assert deck["notes"]["3"]["meta"] == {"status": "generated"}
    assert deck["slides"][2]["note"]["status"] == "generated"


def test_no_courses(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path / "missing")
    out = tmp_path / "empty"
    assert export_courses(out) == 0
    assert json.loads((out / "data/courses.json").read_text()) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/video",
        "https://127.1/v",
        "https://0x7f000001/v",
        "https://0177.0.0.1/v",
        "https://%31%32%37.0.0.1/v",
        "https://127.0.0.1/video",
        "https://100.81.100.96/v",
        "https://192.168.1.2/v",
        "https://demo.internal/v",
        "file:///home/user/video",
        "https://user:password@example.com/v",
        "https://demo.ts.net/v",
    ],
)
def test_private_video_urls_not_published(public_course, tmp_path, url):
    public_course.save_info({"videoUrls": {"recording": url}})
    out = tmp_path / "out"
    export_courses(out)
    assert (
        json.loads((out / "data/fixture/course.json").read_text())["info"]["videoUrls"]
        == {}
    )


def test_course_and_deck_traversal(public_course, tmp_path):
    for course_id in ("../outside", "/tmp", ".hidden"):
        with pytest.raises(ValueError):
            export_courses(tmp_path / "out", [course_id])
    for deck_id in ("../outside", "/tmp", "a/b"):
        with pytest.raises(ValueError):
            export_courses(tmp_path / "out", [public_course.id], [deck_id])
    manifest = public_course.manifest()
    manifest["decks"][0]["id"] = "../outside"
    write_json(public_course.path("generated", "manifest.json"), manifest)
    with pytest.raises(ValueError):
        export_courses(tmp_path / "out")


def test_symlink_asset_cannot_escape(public_course, tmp_path):
    target = public_course.path("notes", "deck", "assets", "架構圖.svg")
    outside = tmp_path / "outside.svg"
    outside.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        export_courses(tmp_path / "out")


def test_unsafe_svg_not_published(public_course, tmp_path):
    write_text(
        public_course.path("notes", "deck", "assets", "架構圖.svg"),
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    )
    with pytest.raises(ValueError, match="SVG"):
        export_courses(tmp_path / "out")


def test_deck_selection_and_partial_transcript(public_course, tmp_path):
    write_json(
        public_course.video_path("recording", "transcript.json"),
        {"partial": True, "segments": [{"text": "草稿"}]},
    )
    out = tmp_path / "out"
    export_courses(out, [public_course.id], ["hidden"])
    assert json.loads((out / "data/fixture/course.json").read_text())["decks"] == []
    assert json.loads(
        (out / "data/fixture/transcripts/recording.json").read_text()
    ) == {"segments": [], "partial": False}


def test_source_destination_overlap_rejected(public_course):
    with pytest.raises(ValueError, match="重疊"):
        export_courses(public_course.dir / "export")


def test_timestamp_meta_is_json_serializable(public_course, tmp_path):
    write_text(
        public_course.note_path("deck", 1),
        "---\nstatus: edited\nupdatedAt: 2026-11-03T00:00:00Z\n---\n手寫筆記",
    )
    out = tmp_path / "out"
    export_courses(out)
    meta = json.loads((out / "data/fixture/decks/deck.json").read_text())["notes"]["1"][
        "meta"
    ]
    assert meta["updatedAt"].startswith("2026-11-03")


def test_course_symlink_cannot_publish_another_course(public_course, tmp_path):
    alias = config.COURSES_DIR / "public"
    alias.symlink_to(public_course.dir, target_is_directory=True)
    out = tmp_path / "out"
    with pytest.raises(OSError):
        export_courses(out, ["public"])
    assert not (out / "data/courses.json").exists()


def test_generated_directory_symlink_rejected(public_course, tmp_path):
    alias = config.COURSES_DIR / "public"
    alias.mkdir()
    (alias / "generated").symlink_to(public_course.gen, target_is_directory=True)
    with pytest.raises(OSError):
        export_courses(tmp_path / "out", ["public"])
