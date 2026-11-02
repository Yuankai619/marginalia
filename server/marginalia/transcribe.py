"""Local speech-to-text with faster-whisper, so lectures never touch a paid API.

Lectures here are mostly English with Mandarin mixed in, so language detection
runs per segment (multilingual=True) instead of once for the whole file. Slide
titles go into the initial prompt to bias the decoder toward the right terms.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from . import config, media
from .store import Course, write_json

Progress = Callable[[float, str], None]


def _vocabulary(course: Course, limit: int = 600) -> str:
    words: list[str] = []
    for d in course.manifest()["decks"]:
        for s in course.slides(d["id"]):
            if s.get("title"):
                words.append(s["title"])
    text = "; ".join(dict.fromkeys(words))
    return text[:limit]


def transcribe_video(course: Course, video_id: str, progress: Progress | None = None, model_name: str | None = None) -> dict:
    from faster_whisper import WhisperModel

    progress = progress or (lambda f, m: None)
    v = course.video(video_id)
    if not v:
        raise KeyError(video_id)
    vdir = course.video_dir(video_id)
    wav = vdir / "audio.wav"
    if not wav.exists():
        progress(0.0, "抽出音訊")
        media.extract_audio(course.dir / v["source"], wav)

    model_name = model_name or config.WHISPER_MODEL
    progress(0.01, f"載入 Whisper 模型 {model_name}")
    model = WhisperModel(model_name, device="auto", compute_type="int8", cpu_threads=config.WHISPER_THREADS)
    prompt = f"{course.info()['title']} lecture. 課程以英文為主，穿插中文。{_vocabulary(course)}"
    segments_iter, info = model.transcribe(
        str(wav),
        multilingual=True,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
        initial_prompt=prompt,
        word_timestamps=False,
    )
    total = info.duration or v.get("duration") or 1
    segs = []
    started = time.time()
    for s in segments_iter:
        text = s.text.strip()
        if not text:
            continue
        segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        if len(segs) % 20 == 0:
            frac = min(s.end / total, 1.0)
            eta = (time.time() - started) / max(frac, 1e-3) * (1 - frac)
            progress(0.02 + 0.97 * frac, f"轉錄中 {s.end / 60:.0f}/{total / 60:.0f} 分鐘，約剩 {eta / 60:.0f} 分鐘")
            # partial saves let the UI show text while the job runs
            write_json(vdir / "transcript.partial.json", {"segments": segs})
    out = {"model": model_name, "language": info.language, "duration": total, "segments": segs}
    write_json(vdir / "transcript.json", out)
    (vdir / "transcript.partial.json").unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    progress(1.0, f"完成：{len(segs)} 段")
    return out
