import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from marginalia import align, ingest, transcribe
from marginalia.store import write_json


def recording(course):
    source = course.materials / "recording.mp4"
    source.write_bytes(b"old")
    course.save_manifest({"decks": [], "videos": [{
        "id": "recording", "source": "materials/recording.mp4", "kind": "video", "date": "2026-09-16",
    }]})
    return source


@pytest.mark.parametrize("change", ["size", "mtime"])
def test_frame_cache_is_reused_only_for_the_same_source(monkeypatch, course, change):
    source = recording(course)
    calls = []

    def sample(*_args, **_kwargs):
        calls.append(True)
        return iter([(1.0, np.full((90, 160), 240 if len(calls) == 1 else 180, np.uint8))])

    monkeypatch.setattr(align.media, "sample_frames", sample)
    first = align.video_crops(course, "recording")
    cached = align.video_crops(course, "recording")
    np.testing.assert_array_equal(cached["crops"], first["crops"])
    assert len(calls) == 1
    stat = source.stat()
    source.write_bytes(b"new long source" if change == "size" else b"new")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    refreshed = align.video_crops(course, "recording")

    assert len(calls) == 2
    assert not np.array_equal(refreshed["crops"], first["crops"])


def test_legacy_frame_cache_without_fingerprint_is_resampled(monkeypatch, course):
    recording(course)
    cache = course.video_path("recording", "frames.npz")
    cache.parent.mkdir(parents=True)
    np.savez(cache, version=align.FRAME_CACHE_VERSION, times=[1], crops=np.zeros((1, 72, 128)))
    calls = []

    def sample(*_args, **_kwargs):
        calls.append(True)
        return iter([])

    monkeypatch.setattr(align.media, "sample_frames", sample)

    assert len(align.video_crops(course, "recording")["times"]) == 0
    assert calls == [True]


def test_transcribe_refreshes_stale_audio_and_records_source_fingerprint(monkeypatch, course):
    source = recording(course)
    fingerprint = course.fingerprint(course.video("recording"))
    wav = course.video_path("recording", "audio.wav")
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"old extracted audio")
    write_json(course.video_path("recording", "audio.source.json"), fingerprint)
    source.write_bytes(b"new full source")
    extracted = []

    def extract(src, out, **_kwargs):
        extracted.append(src)
        out.write_bytes(b"new extracted audio")

    class WhisperModel:
        def __init__(self, *_args, **_kwargs):
            pass

        def transcribe(self, filename, **_kwargs):
            assert wav.read_bytes() == b"new extracted audio"
            return iter([SimpleNamespace(start=0, end=1, text="測試")]), SimpleNamespace(duration=1, language="zh")

    monkeypatch.setattr(transcribe.media, "extract_audio", extract)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=WhisperModel))

    result = transcribe.transcribe_video(course, "recording")

    assert extracted == [source]
    assert result["sourceFingerprint"] == course.fingerprint(course.video("recording"))
    assert course.transcript_current("recording")
    assert not wav.exists()


def test_scan_invalidates_deck_render_and_duration_on_same_size_source_change(monkeypatch, course):
    source = recording(course)
    deck = course.materials / "lecture.pdf"
    deck.write_bytes(b"old")
    probes = []
    monkeypatch.setattr(ingest.media, "duration", lambda p: probes.append(p) or 2.0)
    manifest = ingest.scan(course)
    manifest["decks"][0].update(rendered=True, slideCount=1)
    course.save_manifest(manifest)
    for path in (source, deck):
        stat = path.stat()
        path.write_bytes(b"new")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    updated = ingest.scan(course)

    assert not updated["decks"][0].get("rendered")
    assert probes == [source, source]


def test_transcribe_rejects_internal_audio_alias_before_any_subprocess(monkeypatch, course, tmp_path):
    recording(course)
    directory = course.video_dir("recording")
    directory.mkdir(parents=True)
    outside = tmp_path / "outside-sentinel.wav"
    outside.write_bytes(b"sentinel")
    (directory / "audio.wav").symlink_to("renamed.wav")
    (directory / "renamed.part.wav").symlink_to(outside)
    calls = []
    monkeypatch.setattr(transcribe.media.subprocess, "run", lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(ValueError, match="符號連結"):
        transcribe.transcribe_video(course, "recording")

    assert calls == []
    assert outside.read_bytes() == b"sentinel"
    assert not (directory / "renamed.wav").exists()
    assert not (directory / "audio.part.wav").exists()


def test_frame_cache_rejects_alias_that_changes_implicit_numpy_suffix(monkeypatch, course, tmp_path):
    recording(course)
    directory = course.video_dir("recording")
    directory.mkdir(parents=True)
    outside = tmp_path / "outside-sentinel.npz"
    outside.write_bytes(b"sentinel")
    (directory / "frames.npz").symlink_to("renamed")
    (directory / "renamed.npz").symlink_to(outside)
    calls = []
    monkeypatch.setattr(align.media, "sample_frames", lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(ValueError, match="符號連結"):
        align.video_crops(course, "recording")

    assert calls == []
    assert outside.read_bytes() == b"sentinel"
