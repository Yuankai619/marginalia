import zipfile

import pytest

from marginalia import align, cli, ingest, slides, transcribe
from marginalia.store import Course, write_json


@pytest.mark.parametrize("identifier", ["../escape", "a/b", "/tmp/escape", ".", "..", "a.b", "a\\b", "", "-flag"])
@pytest.mark.parametrize("method", ["deck_dir", "video_dir", "deck", "video", "note_path", "review_path"])
def test_identifiers_are_single_slugs(course, identifier, method):
    args = (identifier, 1) if method in {"note_path", "review_path"} else (identifier,)
    with pytest.raises(ValueError):
        getattr(course, method)(*args)


@pytest.mark.parametrize("source", ["../outside.pdf", "/tmp/outside.pdf", "notes/private.md", "materials/../../outside.pdf"])
def test_source_must_resolve_inside_materials(course, source):
    with pytest.raises(ValueError):
        course.source_path(source)


@pytest.mark.parametrize("area", ["materials", "generated", "notes", "chats"])
def test_area_symlinks_cannot_escape_course(course, tmp_path, area):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = course.dir / area
    if target.exists():
        target.rmdir()
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        course.path(area, "sentinel")
    assert list(outside.iterdir()) == []


def test_course_symlink_cannot_escape_courses_root(course, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        Course("linked").info()


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_source_symlinks_cannot_escape_materials(course, tmp_path, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"sentinel")
    link = course.materials / ("secret.pdf" if kind == "file" else "nested")
    link.symlink_to(outside / "secret.pdf" if kind == "file" else outside, target_is_directory=kind == "directory")
    with pytest.raises(ValueError):
        course.source_path(f"materials/{link.name}" + ("/secret.pdf" if kind == "directory" else ""))
    with pytest.raises(ValueError):
        ingest.scan(course)
    assert (outside / "secret.pdf").read_bytes() == b"sentinel"


@pytest.mark.parametrize("artifact", ["deck.pdf", "slides/001.webp", "thumbs/001.webp", "frames.npz", "transcript.json", "audio.part.wav"])
def test_output_leaf_symlinks_cannot_escape_course(course, tmp_path, artifact):
    outside = tmp_path / "sentinel"
    outside.write_bytes(b"sentinel")
    method = course.deck_path if artifact.startswith(("deck", "slides", "thumbs")) else course.video_path
    target = method("valid", artifact)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside)
    with pytest.raises(ValueError):
        method("valid", artifact)
    assert outside.read_bytes() == b"sentinel"


@pytest.mark.parametrize("command", ["render", "align", "transcribe", "process"])
@pytest.mark.parametrize("malicious", ["id", "source"])
def test_cli_rejects_malicious_manifest_before_media_operations(monkeypatch, course, command, malicious):
    deck = {"id": "deck", "source": "materials/deck.pdf"}
    video = {"id": "video", "source": "materials/video.mp4"}
    for entry in (deck, video):
        entry[malicious] = "../escape"
    write_json(course.path("generated", "manifest.json"), {"decks": [deck], "videos": [video]})
    calls = []
    monkeypatch.setattr(slides, "_to_pdf", lambda *_: calls.append("render"))
    monkeypatch.setattr(align.media, "sample_frames", lambda *_args, **_kwargs: calls.append("align"))
    monkeypatch.setattr(transcribe.media, "extract_audio", lambda *_: calls.append("transcribe"))
    monkeypatch.setattr("sys.argv", ["marginalia", command, course.id])
    with pytest.raises(ValueError):
        cli.main()
    assert calls == []


def test_render_rejects_pdf_symlink_before_copying_source(monkeypatch, course, tmp_path):
    course.save_manifest({"decks": [{"id": "deck", "source": "materials/deck.pdf"}], "videos": []})
    course.source_path("materials/deck.pdf").write_bytes(b"fake pdf")
    outside = tmp_path / "sentinel.pdf"
    outside.write_bytes(b"sentinel")
    target = course.deck_path("deck", "deck.pdf")
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    with pytest.raises(ValueError):
        slides.render_deck(course, "deck")
    assert outside.read_bytes() == b"sentinel"


def test_zip_checks_path_components_and_existing_symlinks(course, tmp_path):
    dest = course.materials / "unpacked"
    outside = tmp_path / "outside"
    outside.mkdir()
    dest.mkdir()
    (dest / "linked").symlink_to(outside, target_is_directory=True)
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("linked/escape.txt", "bad")
    with zipfile.ZipFile(archive) as zf, pytest.raises(RuntimeError):
        ingest._safe_extract(zf, dest)
    assert not (outside / "escape.txt").exists()
