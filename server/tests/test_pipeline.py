import os

import pytest

from marginalia import pipeline
from marginalia.store import write_json


def register(course, decks, videos):
    for entry in decks + videos:
        entry["source"] = f"materials/{entry['id']}.{'pdf' if entry in decks else 'mp4'}"
        course.source_path(entry["source"]).write_bytes(b"fixture")
    course.save_manifest({"decks": decks, "videos": videos})


def test_process_skips_current_outputs_and_only_transcribes_target_videos(monkeypatch, course):
    register(course, [{"id": "deck-one", "rendered": True}, {"id": "deck-two"}], [{"id": "video-one"}, {"id": "video-two"}])
    write_json(course.deck_path("deck-one", "slides.json"), [])
    write_json(course.video_path("video-one", "transcript.json"), {"sourceFingerprint": course.fingerprint(course.video("video-one"))})
    rendered, transcribed = [], []
    monkeypatch.setattr(pipeline.ingest, "scan", lambda _: course.manifest())
    monkeypatch.setattr(pipeline.slides, "render_deck", lambda _, deck, __: rendered.append(deck))
    monkeypatch.setattr(
        pipeline.align, "align_course",
        lambda *_: {"segments": [{"video": "video-one", "deck": "deck-one"}, {"video": "video-two", "deck": "deck-two"}]},
    )
    monkeypatch.setattr(pipeline.transcribe, "transcribe_video", lambda _, video, __: transcribed.append(video))

    result = pipeline.process(course, ["deck-one"])

    assert rendered == []
    assert transcribed == []
    assert result["decks"] == ["deck-one"]


@pytest.mark.parametrize("selected", [None, ["deck-one"]])
@pytest.mark.parametrize("unmatched_segments", [[], [{"video": "unmatched", "deck": None}]])
def test_process_transcribes_audio_and_unaligned_videos(monkeypatch, course, selected, unmatched_segments):
    register(course, [{"id": "deck-one"}, {"id": "deck-two"}], [
        {"id": "audio", "kind": "audio"}, {"id": "unmatched", "kind": "video"}, {"id": "other", "kind": "video"},
    ])
    transcribed = []
    monkeypatch.setattr(pipeline.ingest, "scan", lambda _: course.manifest())
    monkeypatch.setattr(pipeline.slides, "render_deck", lambda *_: None)
    monkeypatch.setattr(
        pipeline.align, "align_course",
        lambda *_: {"segments": [{"video": "other", "deck": "deck-two"}] + unmatched_segments},
    )
    monkeypatch.setattr(pipeline.transcribe, "transcribe_video", lambda _, video, __: transcribed.append(video))

    result = pipeline.process(course, selected)

    expected = ["audio", "unmatched"] + (["other"] if selected is None else [])
    assert transcribed == expected
    assert result["transcribed"] == expected


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_process_transcribes_a_course_without_slides(monkeypatch, course, kind):
    register(course, [], [{"id": "recording", "kind": kind, "date": "2026-09-16", "title": "錄音"}])
    transcribed = []
    monkeypatch.setattr(pipeline.ingest, "scan", lambda _: course.manifest())
    monkeypatch.setattr(pipeline.align.media, "sample_frames", lambda *_args, **_kwargs: iter([]))
    monkeypatch.setattr(pipeline.transcribe, "transcribe_video", lambda _, video, __: transcribed.append(video))

    result = pipeline.process(course)

    assert transcribed == ["recording"]
    assert result["transcribed"] == ["recording"]


@pytest.mark.parametrize("change", ["size", "mtime", "legacy"])
def test_process_retranscribes_replaced_sources_with_real_scan(monkeypatch, course, change):
    source = course.materials / "recording.mp4"
    source.write_bytes(b"old")
    monkeypatch.setattr(pipeline.ingest.media, "duration", lambda _: 2.0)
    pipeline.ingest.scan(course)
    fingerprint = course.fingerprint(course.video("recording"))
    write_json(course.video_path("recording", "transcript.json"), {"sourceFingerprint": fingerprint} if change != "legacy" else {"segments": []})
    if change == "size":
        source.write_bytes(b"new full recording")
    elif change == "mtime":
        source.write_bytes(b"new")
        os.utime(source, ns=(fingerprint["mtimeNs"] + 1_000_000, fingerprint["mtimeNs"] + 1_000_000))
    transcribed = []
    monkeypatch.setattr(pipeline.align, "align_course", lambda *_: {"segments": []})
    monkeypatch.setattr(pipeline.transcribe, "transcribe_video", lambda _, video, __: transcribed.append(video))

    result = pipeline.process(course)

    assert transcribed == ["recording"]
    assert result["transcribed"] == ["recording"]
