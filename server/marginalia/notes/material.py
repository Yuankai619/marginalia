"""Everything a writer or reviewer needs to know about one slide, gathered from disk and rendered as prompt text."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..align import slide_ranges
from ..store import Course, read_json, slide_name

MIN_RANGE = 6.0  # on-screen stretches shorter than this are usually alignment flicker
PAD = 5.0  # seconds of transcript kept around each on-screen range; teachers often start a point just before flipping
MAX_TRANSCRIPT_CHARS = 30_000  # ~50 minutes of speech; a slide that stays up longer gets its tail cut
# per-section caps so one slide's material stays near 55k chars however big the deck or the note gets
SLIDE_TEXT_CHARS = 8_000
OUTLINE_CHARS = 6_000
NOTE_CHARS = 20_000
TITLE_CHARS = 200
MAX_RANGES = 20


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n（以下截斷，原文共 {len(text)} 字）"


def clock(seconds: float) -> str:
    s = round(seconds)  # the same rounding as every t= we write, so label and seek target agree
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def load_transcript(course: Course, video: str) -> tuple[list[dict], bool]:
    """Segments and whether they are partial (transcription still running or not started)."""
    full = course.transcript(video)
    if full:
        return full.get("segments", []), False
    part = read_json(course.video_dir(video) / "transcript.partial.json") or {}
    return part.get("segments", []), True


@dataclass
class Material:
    deck: dict
    slide: dict
    image: Path
    assets: Path  # notes/<deck>/assets, where user-supplied images for the note live
    prev_title: str | None
    next_title: str | None
    outline: str
    ranges: list[dict]
    lines: list[dict] = field(default_factory=list)  # {video, start, text}
    partial: bool = False  # some on-screen range has no transcript yet
    untaught: bool = False  # this deck was aligned, but this slide has no on-screen ranges

    inputs: str = ""  # fingerprint of everything alignment/transcription contributed to this slide

    @property
    def index(self) -> int:
        return self.slide["index"]

    @property
    def images(self) -> list[Path]:
        return [self.image] if self.image.exists() else []

    @property
    def videos(self) -> list[str]:
        return list(dict.fromkeys(r["video"] for r in self.ranges))


def outline(slides: list[dict]) -> str:
    return "\n".join(f"{s['index']}. {s.get('title') or ''}".rstrip() for s in slides)


class Gatherer:
    """Builds Material for slides of one deck, caching the deck's slides and each video's transcript."""

    def __init__(self, course: Course, deck_id: str):
        deck = course.deck(deck_id)
        if not deck:
            raise KeyError(deck_id)
        self.course, self.deck = course, deck
        self.slides = course.slides(deck_id)
        self.outline = outline(self.slides)
        self._transcripts: dict[str, tuple[list[dict], bool]] = {}
        # without any alignment for the deck we can't tell skipped slides apart; writers then work from slides only
        alignment = course.alignment()
        segments = alignment.get("segments", [])
        self.aligned = any(s["deck"] == deck_id for s in segments)
        # an unaligned deck is only "not done yet" while some video still waits for alignment; a course without
        # recordings, audio (nothing to align), or a deck never shown in one gets final slide-only notes
        done = set(alignment.get("videos") or {}) | {s["video"] for s in segments}
        videos = [v for v in course.manifest()["videos"] if v.get("kind") != "audio"]
        self.pending = sorted(v["id"] for v in videos if v["id"] not in done)
        self.waiting = not self.aligned and bool(self.pending)

    def transcript(self, video: str) -> tuple[list[dict], bool]:
        if video not in self._transcripts:
            self._transcripts[video] = load_transcript(self.course, video)
        return self._transcripts[video]

    def get(self, index: int) -> Material:
        if not 1 <= index <= len(self.slides):
            raise IndexError(f"slide {index} not in deck {self.deck['id']}")
        slide = self.slides[index - 1]
        # short flashes are usually alignment noise, but if that is all there is, let the writer judge the transcript
        every = slide_ranges(self.course, self.deck["id"], index, 0.0)
        ranges = [r for r in every if r["end"] - r["start"] >= MIN_RANGE] or every
        lines: list[dict] = []
        partial = self.waiting
        for r in ranges:
            segs, is_partial = self.transcript(r["video"])
            covered_to = segs[-1]["end"] if segs else 0.0
            if is_partial and covered_to < r["end"]:
                partial = True
            for s in segs:
                if s["end"] > r["start"] - PAD and s["start"] < r["end"] + PAD:
                    line = {"video": r["video"], "start": s["start"], "text": s["text"]}
                    if not lines or lines[-1] != line:
                        lines.append(line)
        return Material(
            deck=self.deck,
            slide=slide,
            image=self.course.deck_dir(self.deck["id"]) / "slides" / f"{slide_name(index)}.webp",
            assets=self.course.notes_dir / self.deck["id"] / "assets",
            prev_title=self.slides[index - 2].get("title") if index > 1 else None,
            next_title=self.slides[index].get("title") if index < len(self.slides) else None,
            outline=self.outline,
            ranges=ranges,
            lines=lines,
            partial=partial,
            untaught=self.aligned and not ranges,
            inputs=self._fingerprint(ranges, lines, partial),
        )

    def _fingerprint(self, ranges: list[dict], lines: list[dict], partial: bool) -> str:
        """Content, not files: what this slide's note was written from. Rewriting alignment.json or a transcript
        with the same content (every pipeline run re-aligns) leaves it unchanged, so a partial note is only
        regenerated when its material really moved on."""
        used = {
            "ranges": [[r["video"], r["start"], r["end"]] for r in ranges],
            "lines": [[ln["video"], ln["start"], ln["text"]] for ln in lines],
            "partial": partial,
            "aligned": self.aligned,
            "pending": self.pending if self.waiting else [],
        }
        return hashlib.sha256(json.dumps(used, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def transcript_text(m: Material) -> str:
    out, size = [], 0
    for ln in m.lines:
        row = f"[{ln['video']} t={round(ln['start'])} {clock(ln['start'])}] {ln['text']}"
        size += len(row) + 1
        if size > MAX_TRANSCRIPT_CHARS:
            out.append("（逐字稿過長，後面截斷）")
            break
        out.append(row)
    return "\n".join(out)


def render(m: Material) -> str:
    """The slide's material as one block of prompt text (the slide image is attached separately)."""
    s = m.slide
    parts = [
        f"# 簡報：{clip(m.deck.get('title') or m.deck['id'], TITLE_CHARS)}（{m.deck['id']}）",
        f"## 整份簡報大綱\n{clip(m.outline, OUTLINE_CHARS)}",
        f"## 本頁：第 {m.index} 頁「{clip(s.get('title') or '', TITLE_CHARS)}」",
        f"前一頁：{clip(m.prev_title or '（無）', TITLE_CHARS)}；後一頁：{clip(m.next_title or '（無）', TITLE_CHARS)}",
        f"### 投影片文字\n{clip((s.get('text') or '').strip(), SLIDE_TEXT_CHARS) or '（無文字）'}",
    ]
    if (s.get("speakerNotes") or "").strip():
        parts.append(f"### 講者備註\n{clip(s['speakerNotes'].strip(), SLIDE_TEXT_CHARS)}")
    if m.ranges:
        spans = "、".join(f"{r['video']} {clock(r['start'])}–{clock(r['end'])}（t={r['start']:.0f}–{r['end']:.0f}）" for r in m.ranges[:MAX_RANGES])
        if len(m.ranges) > MAX_RANGES:
            spans += f"，另有 {len(m.ranges) - MAX_RANGES} 段"
        parts.append(f"### 這頁出現在影片的時間\n{spans}")
    else:
        parts.append("### 這頁出現在影片的時間\n（對齊結果裡這頁沒有出現在任何影片上）")
    if m.lines:
        note = "\n（注意：逐字稿還在轉錄中，這頁後段可能缺字。）" if m.partial else ""
        parts.append(
            "### 老師在這頁的逐字稿\n"
            "每行開頭是 [影片 id t=秒數 時:分:秒]。語音辨識結果，有錯字，請依投影片修正後再理解。"
            f"{note}\n{transcript_text(m)}"
        )
    elif m.ranges:
        parts.append("### 老師在這頁的逐字稿\n（逐字稿還沒轉好，只能依投影片與講者備註寫，不要附時間點。）")
    return "\n\n".join(parts)
