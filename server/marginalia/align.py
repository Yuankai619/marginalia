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

from . import config, media
from .store import Course, slide_name, write_json

CW, CH = 128, 72  # stored crop of the slide area per frame
STEP = 2.0  # seconds between sampled frames
NONE = -1
TITLE_ROWS = (3, 12)  # exclude the running header and first body-text line
FRAME_CACHE_VERSION = 6


def _crop(gray: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(gray).resize((CW, CH), Image.Resampling.BILINEAR), np.uint8)


def _unit(v: np.ndarray) -> np.ndarray:
    v = v.reshape(len(v), -1).astype(np.float32)
    v = v - v.mean(axis=1, keepdims=True)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-6)


def _number_crop(gray: np.ndarray) -> np.ndarray:
    """Keep the aspect of the page-number ink; no OCR or external model."""
    h, w = gray.shape
    patch = gray[round(h * 0.015):round(h * 0.07), round(w * 0.94):round(w * 0.995)]
    ys, xs = np.where(patch < 235)
    canvas = Image.new("L", (16, 16))
    if len(xs):
        ink = Image.fromarray(255 - patch[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        scale = 16 / max(ink.size)
        ink = ink.resize((max(1, round(ink.width * scale)), max(1, round(ink.height * scale))), Image.Resampling.BILINEAR)
        canvas.paste(ink, ((16 - ink.width) // 2, (16 - ink.height) // 2))
    return np.asarray(canvas)


def _number_features(numbers: np.ndarray) -> np.ndarray:
    """Normalize faint thumbnails and low-resolution recording digits alike."""
    out = []
    for number in numbers:
        ink = number > number.max() * 0.7
        ys, xs = np.where(ink)
        if len(xs):
            ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        out.append(np.asarray(Image.fromarray(ink.astype(np.uint8) * 255).resize((16, 16), Image.Resampling.BILINEAR)))
    vectors = np.stack(out).reshape(len(numbers), -1).astype(np.float32)
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-6)


def _features(crops: np.ndarray, numbers: np.ndarray | None = None) -> dict:
    """crops: K x CH x CW uint8. Title-band vectors plus 'ink' maps.

    Slides build up with animations, so the recording often shows only part of
    a slide. Titles are rarely animated, so the title band carries most of the
    identity; ink maps let us ask "is everything on screen also on this slide?"
    """
    a = crops.astype(np.float32)
    t0, t1 = TITLE_ROWS
    titles = []
    for crop in crops:
        band = crop[t0:t1, 5:CW - 8]
        ys, xs = np.where(band < 160)
        if len(xs):
            band = band[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        titles.append(np.asarray(Image.fromarray(band).resize((CW, 16), Image.Resampling.BILINEAR)))
    title = _unit(np.stack(titles))
    bg = np.median(a.reshape(len(a), -1), axis=1)[:, None, None]
    diff = np.abs(a - bg)
    small = diff.reshape(len(a), CH // 2, 2, CW // 2, 2).max(axis=(2, 4))
    ink = small > 45
    pad = np.pad(ink, ((0, 0), (1, 1), (1, 1)))
    dil = np.zeros_like(ink)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            dil |= pad[:, dy : dy + CH // 2, dx : dx + CW // 2]
    out = {"title": title, "ink": ink.reshape(len(a), -1).astype(np.float32), "dil": dil.reshape(len(a), -1).astype(np.float32)}
    if numbers is not None:
        out["number"] = _number_features(numbers)
    return out


def similarity(frames: dict, slides: dict) -> np.ndarray:
    title = frames["title"] @ slides["title"].T
    f_ink = frames["ink"].sum(axis=1, keepdims=True)
    contain = (frames["ink"] @ slides["dil"].T) / np.maximum(f_ink, 1)
    cover = (frames["dil"] @ slides["ink"].T) / np.maximum(slides["ink"].sum(axis=1)[None, :], 1)
    # an almost empty frame (blank screen, camera view) says little either way
    contain = np.where(f_ink < 8, 0.5, contain)
    score = 0.45 * title + 0.4 * contain + 0.15 * cover
    if "number" in frames and "number" in slides:
        numbered = (frames["number"].any(axis=1)[:, None] & slides["number"].any(axis=1)[None, :])
        score = np.where(numbered, 0.65 * score + 0.35 * (frames["number"] @ slides["number"].T), score)
    return score


def _bright_box(img: np.ndarray, thresh: int = 110) -> tuple[int, int, int, int] | None:
    mask = img > thresh
    rows = np.where(mask.mean(axis=1) > 0.3)[0]
    cols = np.where(mask.mean(axis=0) > 0.3)[0]
    if len(rows) < img.shape[0] * 0.25 or len(cols) < img.shape[1] * 0.25:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _fit_slide_aspect(box: tuple[int, int, int, int], shape: tuple[int, int], aspect: float) -> tuple[int, int, int, int]:
    """Trim sharing borders using the closest actual candidate-deck aspect."""
    x0, y0, x1, y1 = box
    h, w = shape
    bw, bh = x1 - x0, y1 - y0
    if bw / bh > aspect:
        inset = (bw - bh * aspect) / 2
        x0, x1 = round(x0 + inset), round(x1 - inset)
    else:
        inset = (bh - bw / aspect) / 2
        y0, y1 = round(y0 + inset), round(y1 - inset)
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def detect_region(frames: np.ndarray, aspects: list[float] | None = None) -> tuple[int, int, int, int]:
    """Bounding box of the shared-slide area, from the median frame."""
    med = np.median(frames[:: max(1, len(frames) // 300)], axis=0).astype(np.uint8)
    box = _bright_box(med)
    h, w = frames.shape[1:]
    return _fit_region(box, (h, w), aspects) if box else (0, 0, w, h)


def _fit_region(box: tuple[int, int, int, int], shape: tuple[int, int], aspects: list[float] | None) -> tuple[int, int, int, int]:
    if not aspects:
        return box
    ratio = (box[2] - box[0]) / (box[3] - box[1])
    return _fit_slide_aspect(box, shape, min(aspects, key=lambda aspect: abs(np.log(aspect / ratio))))


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0.0


def video_crops(course: Course, video_id: str, progress=lambda f, m: None) -> dict:
    """Sample frames, find the slide region per two-minute window, keep small crops."""
    vdir = course.video_dir(video_id)
    v = course.video(video_id)
    if v.get("kind") == "audio":
        return {"times": np.zeros(0), "crops": np.zeros((0, CH, CW), np.uint8), "boxes": np.zeros((0, 4))}
    fingerprint = course.fingerprint(v)
    candidates = set(candidate_decks(course, v["date"]))
    aspects = sorted({
        d["width"] / d["height"] for d in course.manifest()["decks"]
        if d["id"] in candidates and d.get("width", 0) > 0 and d.get("height", 0) > 0
    })
    cache = course.video_path(video_id, "frames.npz")
    if cache.exists():
        with np.load(cache) as d:
            if (
                d.get("version") == FRAME_CACHE_VERSION and "numbers" in d
                and all(d.get(key) == value for key, value in fingerprint.items())
                and np.array_equal(d.get("aspects"), aspects)
            ):
                return {k: d[k] for k in ("times", "crops", "boxes", "numbers")}
    total = v.get("duration") or 1
    times, frames = [], []
    for t, g in media.sample_frames(course.source_path(v["source"]), every=STEP):
        times.append(t)
        frames.append(g)
        if len(times) % 150 == 0:
            progress(0.8 * min(t / total, 1), f"取樣影格 {t / 60:.0f}/{total / 60:.0f} 分鐘")
    if not frames:
        progress(0.8, "沒有可用影格，略過對齊")
        return {"times": np.zeros(0), "crops": np.zeros((0, CH, CW), np.uint8), "boxes": np.zeros((0, 4))}
    arr = np.stack(frames)
    glob_box = detect_region(arr, aspects)
    crops, boxes, numbers = [], [], []
    win = 60
    for s in range(0, len(arr), win):
        chunk = arr[s : s + win]
        local = _bright_box(np.median(chunk, axis=0).astype(np.uint8))
        local = _fit_region(local, arr.shape[1:], aspects) if local else None
        # Browser bars and Webex controls can turn the per-window bright box
        # taller than the slide.  A whole-video median is much more stable;
        # accept a local box only when it agrees with it almost exactly.
        box = local if local and _overlap(local, glob_box) >= 0.96 else glob_box
        x0, y0, x1, y1 = box
        for g in chunk:
            crops.append(_crop(g[y0:y1, x0:x1]))
            numbers.append(_number_crop(g[y0:y1, x0:x1]))
            boxes.append(box)
    out = {
        "times": np.array(times, np.float32),
        "crops": np.stack(crops),
        "boxes": np.array(boxes, np.int16),
        "version": np.array(FRAME_CACHE_VERSION, np.uint8),
        "numbers": np.stack(numbers),
        "aspects": np.array(aspects),
        **{key: np.array(value) for key, value in fingerprint.items()},
    }
    vdir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **out)
    return out


def slide_features(course: Course, deck_ids: list[str]) -> tuple[dict, list[tuple[str, int]]]:
    crops, keys, numbers = [], [], []
    for d in deck_ids:
        n = (course.deck(d) or {}).get("slideCount", 0)
        for i in range(1, n + 1):
            p = course.deck_path(d, "thumbs", f"{slide_name(i)}.webp")
            if p.exists():
                with Image.open(p) as image:
                    gray = np.asarray(image.convert("L"))
                crops.append(_crop(gray))
                numbers.append(_number_crop(gray))
                keys.append((d, i))
    return (_features(np.stack(crops), np.stack(numbers)), keys) if crops else ({}, [])


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
            else:
                # Deck order is unrelated to lecture order; penalize every
                # cross-deck jump equally while allowing any destination page.
                trans[a, b] = -14.0
        deck = deck_index[deck_of[a]]
        trans[a, blank_start + deck] = -5.0
    for deck, name in enumerate(decks):
        blank = blank_start + deck
        trans[blank, blank] = 0.0
        for b, (other, _) in enumerate(keys):
            trans[blank, b] = -5.0 if other == name else -14.0
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


def candidate_decks(course: Course, video_date: str) -> list[str]:
    """Dates are uncertain (often mtime); retain every visible rendered deck."""
    hidden = set(course.info()["hiddenDecks"])
    return [d["id"] for d in course.manifest()["decks"] if d.get("rendered") and d["id"] not in hidden]


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
        if not keys:
            continue
        sub(0.85, "比對投影片")
        sim = similarity(_features(fp["crops"], fp.get("numbers")), slide_ft)
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
    write_json(course.path(config.GENERATED, "alignment.json"), out)
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
