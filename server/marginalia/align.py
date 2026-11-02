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


def detect_region(frames: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box of the shared-slide area, from the median frame."""
    med = np.median(frames[:: max(1, len(frames) // 300)], axis=0).astype(np.uint8)
    box = _bright_box(med)
    h, w = frames.shape[1:]
    return box or (0, 0, w, h)


def video_crops(course: Course, video_id: str, progress=lambda f, m: None) -> dict:
    """Sample frames, find the slide region per two-minute window, keep small crops."""
    vdir = course.video_dir(video_id)
    cache = vdir / "frames.npz"
    if cache.exists():
        d = np.load(cache)
        if "crops" in d:
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
        box = _bright_box(np.median(chunk, axis=0).astype(np.uint8)) or glob_box
        x0, y0, x1, y1 = box
        for g in chunk:
            crops.append(_crop(g[y0:y1, x0:x1]))
            boxes.append(box)
    out = {"times": np.array(times, np.float32), "crops": np.stack(crops), "boxes": np.array(boxes, np.int16)}
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
    """sim: T x N. Returns best state per frame (NONE = no slide visible)."""
    T, N = sim.shape
    tau = 0.04
    emit = np.concatenate([sim / tau + prior[None, :], np.full((T, 1), none_level / tau)], axis=1)
    S = N + 1
    trans = np.full((S, S), -14.0, np.float32)  # arbitrary jump
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
    trans[:N, N] = -6.0
    trans[N, :N] = -6.0
    trans[N, N] = 0.0
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
    path[path == N] = NONE
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


def align_course(course: Course, progress: Callable[[float, str], None] = lambda f, m: None, videos: list[str] | None = None) -> dict:
    info = course.info()
    man = course.manifest()
    decks = [d["id"] for d in man["decks"] if d.get("rendered") and d["id"] not in info["hiddenDecks"]]
    vids = [v for v in man["videos"] if not videos or v["id"] in videos]
    slide_ft, keys = slide_features(course, decks)
    old = course.alignment()
    segments = [s for s in old.get("segments", []) if s["video"] not in {v["id"] for v in vids} and not s.get("manual")]
    manual = [s for s in old.get("segments", []) if s.get("manual")]
    meta = old.get("videos", {})

    for vi, v in enumerate(vids):
        sub = lambda f, m, vi=vi: progress((vi + f) / len(vids), f"{v['title']}：{m}")
        fp = video_crops(course, v["id"], sub)
        if len(fp["times"]) == 0:
            continue
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
