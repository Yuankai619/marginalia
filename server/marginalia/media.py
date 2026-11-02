"""ffmpeg helpers: probing, audio extraction, low-res frame sampling."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import numpy as np


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(path: Path) -> float:
    import av

    with av.open(str(path)) as c:
        if c.duration:
            return c.duration / 1_000_000
        s = c.streams.video[0] if c.streams.video else c.streams.audio[0]
        return float(s.duration * s.time_base) if s.duration else 0.0


def extract_audio(video: Path, out_wav: Path) -> Path:
    """16 kHz mono wav, what whisper wants."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_wav.with_suffix(".part.wav")
    subprocess.run(
        [ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(tmp)],
        check=True,
    )
    tmp.replace(out_wav)
    return out_wav


def sample_frames(video: Path, every: float = 2.0, width: int = 384, height: int = 216) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (seconds, grayscale uint8 HxW) every `every` seconds."""
    proc = subprocess.Popen(
        [
            ffmpeg_exe(), "-loglevel", "error", "-i", str(video),
            "-vf", (
                f"fps=1/{every},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=gray"
            ),
            "-f", "rawvideo", "-",
        ],
        stdout=subprocess.PIPE,
    )
    size = width * height
    i = 0
    try:
        assert proc.stdout
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            # fps filter emits the frame at the middle of each interval
            yield (i + 0.5) * every, np.frombuffer(buf, np.uint8).reshape(height, width)
            i += 1
    finally:
        proc.stdout and proc.stdout.close()
        proc.wait()


def frame_at(video: Path, seconds: float, out: Path, width: int = 960) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg_exe(), "-loglevel", "error", "-y", "-ss", f"{seconds:.2f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)],
        check=True,
    )
    return out
