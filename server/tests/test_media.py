import subprocess

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
