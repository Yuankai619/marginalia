"""System prompts for the course chat agents (qa, interview, review).

The prompt carries a text outline of every deck in the course so the agent can connect the current slide to the
rest of the course, plus everything about the slide the user is on: its text, the teacher's transcript, the current
note and the image path (the agent reads it with the Read tool, its cwd being the course dir).
"""

from __future__ import annotations

from ..notes import notefile
from ..notes.generate import STYLE
from ..notes.material import Gatherer, render
from ..store import Course, read_json

MODES = ("qa", "interview", "review")
OUTLINE_CHARS = 60_000  # whole-course slide text above this falls back to titles + the current deck in full

ROLE = """你是這門課的助教，在學生讀投影片和筆記時陪他學。學生是第一次學作業系統。
- 用繁體中文（台灣用語）回答，技術名詞保留英文。
- 講話直接、具體：用例子、數字、因果。不用 emoji，不用「總之」「值得注意的是」「讓我們」這類套話，不要空泛的開場和結尾。
- 提到老師講過的內容時附時間點，格式 [mm:ss](video:<影片 id>?t=<秒數>)，秒數取逐字稿那一行的 t 值；超過一小時寫 [h:mm:ss](…)。
- 提到投影片時寫出簡報和頁碼，例如「L1 第 7 頁」。
- 逐字稿是語音辨識結果，有錯字；依投影片判斷老師實際說的詞。
- 課程資料都在目前的工作目錄：`generated/decks/<deck>/slides/NNN.webp` 是投影片圖片，`notes/<deck>/NNN.md` 是筆記，
  `generated/videos/<video>/transcript.json` 是逐字稿。需要時用 Read／Grep 去看，不要憑印象回答課程內容。
- 不知道或資料裡沒有的就說沒有，不要編。"""

MODE_RULES = {
    "qa": """## 模式：問答

學生問問題，你回答。
1. 先直接回答問題，一到三段。學生框選了文字或投影片區域時，回答要針對那一塊。
2. 再指回課程：這件事在哪份簡報第幾頁、老師在哪個時間點講到（附連結）。課程沒講到的延伸內容要說明這是補充。
3. 學生的理解有誤時直接指出錯在哪裡。""",
    "interview": """## 模式：口試

你是口試官，用這門課的內容考學生，幫他找出沒懂的地方。
1. 一次只問一題，問完就停，等學生回答。不要自己替學生回答，也不要一次列好幾題。
2. 從目前這頁開始問，之後可以往這份簡報前面的內容、或其他簡報相關的概念延伸。問「為什麼」「如果…會怎樣」「A 和 B 差在哪」，不要考背誦。
3. 學生回答後：先給評分（答對／部分對／答錯）和一句理由，指出漏掉或錯的地方，附上該回去看的投影片頁碼和老師講到的時間點。
4. 接著追問一題（答得好就往深處問，答不好就換個角度問同一個概念），或換下一個概念。
5. 學生說不會、或要求看答案時，才給完整答案。""",
    "review": """## 模式：筆記審稿

學生想知道目前這頁筆記哪裡要改。對照投影片、逐字稿和下面的寫作規範審這份筆記：
1. 正確性：事實錯誤、時間點對不上逐字稿、補充內容寫錯或寫得像老師講的。
2. 文風：AI 味、不清楚、跳步。
3. 涵蓋度：老師講到但筆記漏掉的重點（附時間點）。
條列每個問題：原文、問題、建議改法，嚴重的排前面。沒有問題就說沒有，不要硬挑。學生沒要求就不要整份重寫。""",
}


def _deck_text(course: Course, deck: dict, full: bool) -> str:
    lines = [f"## {deck.get('title') or deck['id']}（{deck['id']}，{deck.get('date') or '日期不明'}）"]
    for s in course.slides(deck["id"]):
        lines.append(f"- 第 {s['index']} 頁：{s.get('title') or ''}")
        if full and (text := (s.get("text") or "").strip()):
            lines.append("  " + " / ".join(ln.strip() for ln in text.splitlines() if ln.strip()))
    return "\n".join(lines)


def course_outline(course: Course, current_deck: str | None = None, limit: int = OUTLINE_CHARS) -> str:
    """Every visible deck's slide text; past `limit`, titles only except the current deck."""
    hidden = set(course.info().get("hiddenDecks", []))
    decks = [d for d in course.manifest()["decks"] if d["id"] not in hidden or d["id"] == current_deck]
    full = "\n\n".join(_deck_text(course, d, True) for d in decks)
    if len(full) <= limit:
        return full
    out = "\n\n".join(_deck_text(course, d, d["id"] == current_deck) for d in decks)
    return out if len(out) <= limit else out[:limit] + "\n（大綱過長，後面截斷）"


def _region_text(region: dict) -> str | None:
    try:
        x, y, w, h = (min(max(float(region.get(k, 0)), 0.0), 1.0) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        return None
    return (
        f"學生在投影片上框選了一塊區域：水平 {x:.0%}–{x + w:.0%}、垂直 {y:.0%}–{y + h:.0%}（從左上角算）。"
        "先讀投影片圖片看那一塊是什麼，回答要聚焦在那裡。"
    )


def _slide_context(course: Course, deck_id: str, index: int, with_review: bool) -> str:
    m = Gatherer(course, deck_id).get(index)
    parts = [
        "# 學生目前在看的投影片",
        f"圖片：`{m.image.relative_to(course.dir)}`（用 Read 讀它，看圖表和版面）",
        render(m),
    ]
    note = notefile.read(course.note_path(deck_id, index))
    if note:
        parts.append(f"## 這頁目前的筆記（status: {note[0].get('status', '?')}）\n\n{note[1]}")
    else:
        parts.append("## 這頁目前的筆記\n（還沒有筆記）")
    if with_review and (rv := read_json(course.review_path(deck_id, index))):
        lines = [f"- [{f.get('severity')}] {f.get('problem')}（{f.get('quote')}）" for f in rv.get("findings", [])]
        if lines:
            parts.append("## 自動審稿先前的意見\n" + "\n".join(lines))
    return "\n\n".join(parts)


def build_system(
    course: Course | str,
    mode: str,
    deck: str | None = None,
    slide: int | None = None,
    selection: dict | None = None,
    region: dict | None = None,
) -> str:
    """System prompt for one chat turn. `selection` is {text, source}; `region` is {x, y, w, h} as slide fractions."""
    if mode not in MODES:
        raise ValueError(f"unknown chat mode: {mode!r}")
    course = course if isinstance(course, Course) else Course(course)
    if deck is not None and course.deck(deck) is None:
        raise KeyError(deck)
    info = course.info()
    parts = [
        ROLE,
        MODE_RULES[mode],
        f"# 課程：{info['title']}" + (f"（{info['subtitle']}）" if info.get("subtitle") else ""),
        f"# 整門課的投影片大綱\n\n{course_outline(course, deck)}",
    ]
    if mode == "review":
        parts.append(f"# 筆記寫作規範\n\n{STYLE}")
    if deck is not None and slide is not None:
        parts.append(_slide_context(course, deck, slide, with_review=mode == "review"))
    if selection and (text := str(selection.get("text") or "").strip()):
        source = {"note": "筆記", "slide": "投影片", "transcript": "逐字稿"}.get(str(selection.get("source")), "畫面")
        parts.append(f"# 學生選取的文字（來自{source}）\n\n> " + text[:4000].replace("\n", "\n> "))
    if isinstance(region, dict) and (text := _region_text(region)):
        parts.append(f"# 學生框選的區域\n\n{text}")
    return "\n\n".join(parts)
