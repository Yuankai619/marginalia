import subprocess
import wave

import pytest

from marginalia import media
from marginalia.align import detect_region


def test_sampling_preserves_a_four_by_three_recordings_aspect(tmp_path):
    source = tmp_path / "fixture.mkv"
    subprocess.run([
        media.ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=white:s=160x120:r=2", "-t", "2", "-c:v", "ffv1", str(source),
    ], check=True)

    frames = list(media.sample_frames(source))

    assert len(frames) == 1
    _, frame = frames[0]
    assert frame.shape == (216, 384)
    assert frame[:, :48].max() == 0
    assert frame[:, 336:].max() == 0
    assert detect_region(frame[None], [4 / 3]) == (48, 0, 336, 216)
    image = media.frame_at(source, 0, tmp_path / "frame.png")
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_audio_extraction_ignores_legacy_temp_symlinks_and_writes_real_wav(tmp_path):
    source = tmp_path / "silent.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0" * 3200)
    root = tmp_path / "generated"
    root.mkdir()
    outside = tmp_path / "outside-sentinel.wav"
    outside.write_bytes(b"sentinel")
    (root / "audio.part.wav").symlink_to(outside)

    result = media.extract_audio(source, root / "audio.wav", root=root)

    assert result.read_bytes().startswith(b"RIFF")
    assert result.read_bytes()[8:12] == b"WAVE"
    with wave.open(str(result), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert len(audio.readframes(1600)) == 3200
    assert outside.read_bytes() == b"sentinel"
    assert list(root.glob(".tmp-*")) == []


def test_audio_extraction_cleans_up_on_ffmpeg_failure(monkeypatch, tmp_path):
    output = tmp_path / "audio.wav"
    output.write_bytes(b"previous completed audio")

    def fail(command, *, stdout, **_kwargs):
        assert command[-1] == "pipe:1"
        assert not stdout.closed
        stdout.write(b"partial")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(media.subprocess, "run", fail)

    with pytest.raises(subprocess.CalledProcessError):
        media.extract_audio(tmp_path / "source.wav", output, root=tmp_path)

    assert output.read_bytes() == b"previous completed audio"
    assert list(tmp_path.glob(".tmp-*")) == []


def test_audio_extraction_checks_actual_destination_before_subprocess(monkeypatch, tmp_path):
    root = tmp_path / "generated"
    root.mkdir()
    outside = tmp_path / "outside-sentinel.wav"
    outside.write_bytes(b"sentinel")
    calls = []
    monkeypatch.setattr(media.subprocess, "run", lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(ValueError):
        media.extract_audio(tmp_path / "source.wav", outside, root=root)
    with pytest.raises(ValueError):
        media.extract_audio(tmp_path / "source.wav", root / ".." / outside.name, root=root)
    (root / "audio.wav").symlink_to("renamed.wav")
    with pytest.raises(ValueError, match="符號連結"):
        media.extract_audio(tmp_path / "source.wav", root / "audio.wav", root=root)

    assert calls == []
    assert outside.read_bytes() == b"sentinel"
    assert list(root.glob(".tmp-*")) == []


@pytest.mark.parametrize("fail", [False, True])
def test_audio_replace_and_cleanup_pin_directory_after_parent_swap(monkeypatch, tmp_path, fail):
    root = tmp_path / "generated"
    directory = root / "videos" / "recording"
    directory.mkdir(parents=True)
    output = directory / "audio.wav"
    output.write_bytes(b"previous audio")
    saved = directory.with_name("saved")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "audio.wav").write_bytes(b"outside sentinel")
    temp_names = []

    def replace_parent(command, *, stdout, **_kwargs):
        stdout.write(b"new audio")
        name = next(directory.glob(".tmp-*")).name
        temp_names.append(name)
        directory.rename(saved)
        directory.symlink_to(outside, target_is_directory=True)
        (outside / name).write_bytes(b"outside temp sentinel")
        if fail:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(media.subprocess, "run", replace_parent)

    if fail:
        with pytest.raises(subprocess.CalledProcessError):
            media.extract_audio(tmp_path / "source.wav", output, root=root)
    else:
        media.extract_audio(tmp_path / "source.wav", output, root=root)

    assert (saved / "audio.wav").read_bytes() == (b"previous audio" if fail else b"new audio")
    assert list(saved.glob(".tmp-*")) == []
    assert (outside / "audio.wav").read_bytes() == b"outside sentinel"
    assert (outside / temp_names[0]).read_bytes() == b"outside temp sentinel"


def test_audio_extraction_rejects_replaced_temp_entry(monkeypatch, tmp_path):
    root = tmp_path / "generated"
    root.mkdir()
    outside = tmp_path / "outside-sentinel.wav"
    outside.write_bytes(b"sentinel")
    output = root / "audio.wav"
    output.write_bytes(b"previous audio")

    def replace_temp(_command, *, stdout, **_kwargs):
        stdout.write(b"new audio")
        temp = next(root.glob(".tmp-*"))
        temp.unlink()
        temp.symlink_to(outside)

    monkeypatch.setattr(media.subprocess, "run", replace_temp)

    with pytest.raises(ValueError, match="遭置換"):
        media.extract_audio(tmp_path / "source.wav", output, root=root)

    assert outside.read_bytes() == b"sentinel"
    assert output.read_bytes() == b"previous audio"
    assert list(root.glob(".tmp-*")) == []


def test_audio_extraction_rejects_root_swapped_before_directory_is_pinned(monkeypatch, tmp_path):
    root = tmp_path / "generated"
    directory = root / "videos" / "recording"
    directory.mkdir(parents=True)
    output = directory / "audio.wav"
    outside = tmp_path / "outside"
    sentinel = outside / "videos" / "recording" / "audio.wav"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"sentinel")
    root.rename(tmp_path / "saved")
    root.symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr(media.subprocess, "run", lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(OSError):
        media.extract_audio(tmp_path / "source.wav", output, root=root)

    assert calls == []
    assert sentinel.read_bytes() == b"sentinel"
    assert list(sentinel.parent.glob(".tmp-*")) == []


def test_frame_extraction_rejects_output_symlink_before_subprocess(monkeypatch, tmp_path):
    sentinel = tmp_path / "sentinel.png"
    sentinel.write_bytes(b"sentinel")
    output = tmp_path / "frame.png"
    output.symlink_to(sentinel)
    calls = []
    monkeypatch.setattr(media.subprocess, "run", lambda *_args, **_kwargs: calls.append(True))

    with pytest.raises(ValueError, match="符號連結"):
        media.frame_at(tmp_path / "source.mp4", 0, output)

    assert calls == []
    assert sentinel.read_bytes() == b"sentinel"
