"""Work out which slide is on screen at every moment of every video.

Videos and decks are not one-to-one: a deck can run across two recordings and a
recording can cover the end of one deck and the start of the next. So every
sampled frame is compared against every slide of every deck, and a Viterbi pass
over (deck, slide) states picks the most plausible path, favouring "stay on the
same slide" and "go to the next slide" over random jumps.

Frame matching is pure numpy on tiny greyscale fingerprints: no model, no API.
Lecture recordings (Webex, Teams, OBS…) put the shared slide in a bright
rectangle, so we find that rectangle first and compare only what is inside it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

import numpy as np
from PIL import Image

from . import media
from .store import Course, slide_name, write_json

CW, CH = 128, 72  # stored crop of the slide area per frame
STEP = 2.0  # seconds between sampled frames
NONE = -1
TITLE_ROWS = (3, 17)  # title band in a 72-row crop (skips the running header line)
FRAME_CACHE_VERSION = 3


def _crop(gray: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(gray).resize((CW, CH), Image.Resampling.BILINEAR), np.uint8)


def _unit(v: np.ndarray) -> np.ndarray:
    v = v.reshape(len(v), -1).astype(np.float32)
    v = v - v.mean(axis=1, keepdims=True)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-6)


def _features(crops: np.ndarray) -> dict:
    """crops: K x CH x CW uint8. Title-band vectors plus 'ink' maps.

    Slides build up with animations, so the recording often shows only part of
    a slide. Titles are rarely animated, so the title band carries most of the
    identity; ink maps let us ask "is everything on screen also on this slide?"
    """
    a = crops.astype(np.float32)
    t0, t1 = TITLE_ROWS
    band = a[:, t0:t1]
    grad = np.abs(np.diff(band, axis=2))[:, :-1] + np.abs(np.diff(band, axis=1))[:, :, :-1]
    title = np.concatenate([_unit(band), _unit(grad)], axis=1) / np.sqrt(2)
    bg = np.median(a.reshape(len(a), -1), axis=1)[:, None, None]
    diff = np.abs(a - bg)
    small = diff.reshape(len(a), CH // 2, 2, CW // 2, 2).max(axis=(2, 4))
    ink = small > 45
    pad = np.pad(ink, ((0, 0), (1, 1), (1, 1)))
    dil = np.zeros_like(ink)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            dil |= pad[:, dy : dy + CH // 2, dx : dx + CW // 2]
    return {"title": title, "ink": ink.reshape(len(a), -1).astype(np.float32), "dil": dil.reshape(len(a), -1).astype(np.float32)}


def similarity(frames: dict, slides: dict) -> np.ndarray:
    title = frames["title"] @ slides["title"].T
    f_ink = frames["ink"].sum(axis=1, keepdims=True)
    contain = (frames["ink"] @ slides["dil"].T) / np.maximum(f_ink, 1)
    cover = (frames["dil"] @ slides["ink"].T) / np.maximum(slides["ink"].sum(axis=1)[None, :], 1)
    # an almost empty frame (blank screen, camera view) says little either way
    contain = np.where(f_ink < 8, 0.5, contain)
    return 0.45 * title + 0.4 * contain + 0.15 * cover


def _bright_box(img: np.ndarray, thresh: int = 110) -> tuple[int, int, int, int] | None:
    mask = img > thresh
    rows = np.where(mask.mean(axis=1) > 0.3)[0]
    cols = np.where(mask.mean(axis=0) > 0.3)[0]
    if len(rows) < img.shape[0] * 0.25 or len(cols) < img.shape[1] * 0.25:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _fit_slide_aspect(box: tuple[int, int, int, int], shape: tuple[int, int]) -> tuple[int, int, int, int]:
    """Trim a bright sharing rectangle to the 16:9 slide inside its border."""
    x0, y0, x1, y1 = box
    h, w = shape
    bw, bh = x1 - x0, y1 - y0
    if bw / bh > 16 / 9:
        inset = (bw - bh * 16 / 9) / 2
        x0, x1 = round(x0 + inset), round(x1 - inset)
    else:
        inset = (bh - bw * 9 / 16) / 2
        y0, y1 = round(y0 + inset), round(y1 - inset)
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def detect_region(frames: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the shared-slide area, from the median frame."""
    med = np.median(frames[:: max(1, len(frames) // 300)], axis=0).astype(np.uint8)
    box = _bright_box(med)
    h, w = frames.shape[1:]
    return _fit_slide_aspect(box, (h, w)) if box else (0, 0, w, h)


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0.0


def video_crops(course: Course, video_id: str, progress=lambda f, m: None) -> dict:
    """Sample frames, find the slide region per two-minute window, keep small crops."""
    vdir = course.video_dir(video_id)
    cache = vdir / "frames.npz"
    if cache.exists():
        d = np.load(cache)
        if d.get("version") == FRAME_CACHE_VERSION and "crops" in d:
            return {k: d[k] for k in ("times", "crops", "boxes")}
    v = course.video(video_id)
    if v.get("kind") == "audio":
        return {"times": np.zeros(0), "crops": np.zeros((0, CH, CW), np.uint8), "boxes": np.zeros((0, 4))}
    total = v.get("duration") or 1
    times, frames = [], []
    for t, g in media.sample_frames(course.dir / v["source"], every=STEP):
        times.append(t)
        frames.append(g)
        if len(times) % 150 == 0:
            progress(0.8 * min(t / total, 1), f"取樣影格 {t / 60:.0f}/{total / 60:.0f} 分鐘")
    arr = np.stack(frames)
    glob_box = detect_region(arr)
    crops, boxes = [], []
    win = 60
    for s in range(0, len(arr), win):
        chunk = arr[s : s + win]
        local = _bright_box(np.median(chunk, axis=0).astype(np.uint8))
        local = _fit_slide_aspect(local, arr.shape[1:]) if local else None
        # Browser bars and Webex controls can turn the per-window bright box
        # taller than the slide.  A whole-video median is much more stable;
        # accept a local box only when it agrees with it almost exactly.
        box = local if local and _overlap(local, glob_box) >= 0.96 else glob_box
        x0, y0, x1, y1 = box
        for g in chunk:
            crops.append(_crop(g[y0:y1, x0:x1]))
            boxes.append(box)
    out = {
        "times": np.array(times, np.float32),
        "crops": np.stack(crops),
        "boxes": np.array(boxes, np.int16),
        "version": np.array(FRAME_CACHE_VERSION, np.uint8),
    }
    vdir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **out)
    return out


def slide_features(course: Course, deck_ids: list[str]) -> tuple[dict, list[tuple[str, int]]]:
    crops, keys = [], []
    for d in deck_ids:
        thumbs = course.deck_dir(d) / "thumbs"
        n = (course.deck(d) or {}).get("slideCount", 0)
        for i in range(1, n + 1):
            p = thumbs / f"{slide_name(i)}.webp"
            if p.exists():
                crops.append(_crop(np.asarray(Image.open(p).convert("L"))))
                keys.append((d, i))
    return _features(np.stack(crops)), keys


def _viterbi(sim: np.ndarray, keys: list[tuple[str, int]], prior: np.ndarray, none_level: float) -> np.ndarray:
    """sim: T x N. Returns best state per frame (NONE = no slide visible).

    A separate no-slide state is kept for each deck.  The earlier single
    no-slide state let the path use a one-frame blank interval to jump from
    any deck to any other deck, which was particularly harmful when animated
    slides had weak visual scores.
    """
    T, N = sim.shape
    tau = 0.04
    decks = list(dict.fromkeys(deck for deck, _ in keys))
    deck_index = {deck: i for i, deck in enumerate(decks)}
    # slide states, one persistent blank state per deck, then the initial blank
    blank_start = N
    initial_blank = N + len(decks)
    S = initial_blank + 1
    emit = np.full((T, S), none_level / tau, np.float32)
    emit[:, :N] = sim / tau + prior[None, :]
    trans = np.full((S, S), -1_000_000.0, np.float32)
    deck_of = [k[0] for k in keys]
    for a in range(N):
        for b in range(N):
            if deck_of[a] == deck_of[b]:
                gap = keys[b][1] - keys[a][1]
                if gap == 0:
                    trans[a, b] = 0.0
                elif gap == 1:
                    trans[a, b] = -3.0
                elif -3 <= gap <= 4:
                    trans[a, b] = -6.0 - abs(gap)  # flipping back or skipping a few
                else:
                    trans[a, b] = -10.0
        deck = deck_index[deck_of[a]]
        trans[a, blank_start + deck] = -5.0
        # A lecture normally moves forwards through decks.  Requiring the
        # first few slides prevents an early false match from landing midway
        # through a later deck.
        if deck + 1 < len(decks):
            for b, (other, page) in enumerate(keys):
                if other == decks[deck + 1] and page <= 3:
                    trans[a, b] = -14.0
    for deck, name in enumerate(decks):
        blank = blank_start + deck
        trans[blank, blank] = 0.0
        for b, (other, page) in enumerate(keys):
            if other == name:
                trans[blank, b] = -5.0
            elif deck + 1 < len(decks) and other == decks[deck + 1] and page <= 3:
                trans[blank, b] = -14.0
    trans[initial_blank, initial_blank] = 0.0
    for b in range(N):
        trans[initial_blank, b] = -7.0
    score = emit[0].copy()
    back = np.zeros((T, S), np.int32)
    for t in range(1, T):
        cand = score[:, None] + trans
        back[t] = np.argmax(cand, axis=0)
        score = cand[back[t], np.arange(S)] + emit[t]
    path = np.zeros(T, np.int32)
    path[-1] = int(np.argmax(score))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    path[path >= N] = NONE
    return path


def _deck_prior(course: Course, keys, video_date: str) -> np.ndarray:
    """Tiny nudge so that, among near-identical deck versions, the one dated
    closest to (and not after) the lecture wins."""
    vd = date.fromisoformat(video_date)
    out = np.zeros(len(keys), np.float32)
    cache: dict[str, float] = {}
    for i, (d, _) in enumerate(keys):
        if d not in cache:
            dd = date.fromisoformat((course.deck(d) or {}).get("date", video_date))
            days = (vd - dd).days
            cache[d] = -0.05 * days if days >= 0 else -0.5 - 0.1 * abs(days)
            cache[d] = max(cache[d], -3.0)
        out[i] = cache[d]
    return out


def _deck_family(deck_id: str) -> str:
    """Remove the trailing date used to distinguish archived deck versions."""
    return re.sub(r"[-_]?(?:20)?\d{6,8}(?:v\d+)?$", "", deck_id, flags=re.IGNORECASE).rstrip("-_")


def candidate_decks(course: Course, video_date: str) -> list[str]:
    """Keep the latest deck version that was available on the lecture date."""
    hidden = set(course.info()["hiddenDecks"])
    chosen: dict[str, dict] = {}
    for deck in course.manifest()["decks"]:
        if not deck.get("rendered") or deck["id"] in hidden or deck.get("date", "") > video_date:
            continue
        family = _deck_family(deck["id"])
        if family not in chosen or deck["date"] > chosen[family]["date"]:
            chosen[family] = deck
    return [deck["id"] for deck in chosen.values()]


def align_course(course: Course, progress: Callable[[float, str], None] = lambda f, m: None, videos: list[str] | None = None) -> dict:
    man = course.manifest()
    vids = [v for v in man["videos"] if not videos or v["id"] in videos]
    old = course.alignment()
    segments = [s for s in old.get("segments", []) if s["video"] not in {v["id"] for v in vids} and not s.get("manual")]
    manual = [s for s in old.get("segments", []) if s.get("manual")]
    meta = old.get("videos", {})

    for vi, v in enumerate(vids):
        sub = lambda f, m, vi=vi, v=v: progress((vi + f) / len(vids), f"{v['title']}：{m}")
        fp = video_crops(course, v["id"], sub)
        if len(fp["times"]) == 0:
            continue
        decks = candidate_decks(course, v["date"])
        if not decks:
            continue
        slide_ft, keys = slide_features(course, decks)
        sub(0.85, "比對投影片")
        sim = similarity(_features(fp["crops"]), slide_ft)
        path = _viterbi(sim, keys, _deck_prior(course, keys, v["date"]), none_level=0.45)
        times = fp["times"]
        segs: list[dict] = []
        for t, st in enumerate(path):
            start = float(times[t] - STEP / 2)
            end = float(times[t] + STEP / 2)
            key = None if st == NONE else keys[st]
            score = float(sim[t, st]) if st != NONE else float(sim[t].max())
            if segs and segs[-1]["_key"] == key:
                segs[-1]["end"] = end
                segs[-1]["_scores"].append(score)
            else:
                segs.append({"_key": key, "start": max(0.0, start), "end": end, "_scores": [score]})
        for s in segs:
            k = s.pop("_key")
            sc = s.pop("_scores")
            segments.append({
                "video": v["id"], "start": round(s["start"], 1), "end": round(min(s["end"], v.get("duration") or s["end"]), 1),
                "deck": k[0] if k else None, "slide": k[1] if k else None, "score": round(float(np.mean(sc)), 3),
            })
        meta[v["id"]] = {"step": STEP, "region": [int(x) for x in np.median(fp["boxes"], axis=0)], "frameSize": [384, 216]}

    # manual edits from the UI win over the automatic pass for the ranges they cover
    for m in manual:
        segments = [s for s in segments if not (s["video"] == m["video"] and s["start"] >= m["start"] and s["end"] <= m["end"])]
    segments += manual
    segments.sort(key=lambda s: ([v["id"] for v in man["videos"]].index(s["video"]) if course.video(s["video"]) else 99, s["start"]))
    out = {"videos": meta, "segments": segments}
    write_json(course.gen / "alignment.json", out)
    progress(1.0, f"完成：{sum(1 for s in segments if s['deck'])} 個片段")
    return out


def slide_ranges(course: Course, deck: str, index: int, min_len: float = 6.0) -> list[dict]:
    """Every video range where this slide was on screen, oldest first."""
    order = {v["id"]: i for i, v in enumerate(course.manifest()["videos"])}
    out = [s for s in course.alignment()["segments"] if s["deck"] == deck and s["slide"] == index and s["end"] - s["start"] >= min_len]
    return sorted(out, key=lambda s: (order.get(s["video"], 99), s["start"]))


def deck_coverage(course: Course, deck: str) -> dict:
    """Per-slide seconds on screen and where the deck starts and ends."""
    segs = [s for s in course.alignment()["segments"] if s["deck"] == deck]
    per: dict[int, float] = {}
    for s in segs:
        per[s["slide"]] = per.get(s["slide"], 0) + s["end"] - s["start"]
    return {"seconds": per, "videos": sorted({s["video"] for s in segs})}
