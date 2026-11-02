"""Model-free style checks from style.md: banned phrases, emoji, bold density, timestamp links."""

from __future__ import annotations

import re

from .material import PAD, Material, clock

BANNED = [
    "總之", "總而言之", "綜上所述", "值得注意的是", "值得一提的是", "讓我們", "我們來看看", "扮演著", "扮演重要",
    "扮演關鍵", "至關重要", "不可或缺", "的世界裡", "深入淺出", "一探究竟", "希望這份筆記", "本頁介紹", "這一頁主要",
]  # fmt: skip
NOT_ONLY = re.compile(r"不僅[^。！？\n]{0,40}更")
FIRST_THEN = re.compile(r"首先[^#]{0,400}其次")
# mainland usage -> Taiwan usage
MAINLAND = {
    "內存": "記憶體", "数据": "資料", "數據": "資料", "默認": "預設", "信息": "資訊", "視頻": "影片", "軟件": "軟體",
    "硬件": "硬體", "調用": "呼叫", "進程": "process", "線程": "thread", "緩存": "快取", "接口": "介面",
}  # fmt: skip
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⭐⬆⬇⬅➡✅❌✨]")
BOLD = re.compile(r"\*\*[^*\n]+\*\*")
QUESTION_HEADING = re.compile(r"^#+\s.*[?？]\s*$", re.MULTILINE)
LINK = re.compile(r"\[([^\]\n]*)\]\(video:([^)\s?]*)\?t=([^)\s]*)\)")
SECONDS = re.compile(r"\d{1,6}(?:\.\d+)?")
MAX_BOLD = 3
LINE_SLACK = 3.0  # seconds a cited t may sit from the start of a transcript line


def _finding(severity: str, quote: str, problem: str, fix: str) -> dict:
    return {"reviewer": "rules", "severity": severity, "quote": quote, "problem": problem, "fix": fix}


def _context(text: str, start: int, end: int, pad: int = 12) -> str:
    return text[max(0, start - pad) : end + pad].replace("\n", " ").strip()


def normalize_links(body: str) -> str:
    """Rewrite each timestamp label from its t= value (rounded to whole seconds) so the chip text never disagrees
    with the seek target. Links whose t= is not a plain number are left for `check_links` to report."""

    def fix(m: re.Match) -> str:
        if not SECONDS.fullmatch(m.group(3)):
            return m.group(0)
        t = round(float(m.group(3)))
        return f"[{clock(t)}](video:{m.group(2)}?t={t})"

    return LINK.sub(fix, body)


def check_links(body: str, m: Material) -> list[dict]:
    out = []
    videos = set(m.videos)
    for lk in LINK.finditer(body):
        label, video, t = lk.groups()
        quote = _context(body, lk.start(), lk.end())
        if not SECONDS.fullmatch(t):
            out.append(_finding("high", quote, f"時間點 t={t} 不是秒數。", "改成逐字稿裡那一句的秒數。"))
            continue
        sec = float(t)
        if video not in videos:
            out.append(_finding("high", quote, f"影片 {video} 不是這頁出現的影片。", "改用這頁出現的影片與逐字稿裡的時間。"))
        elif m.lines:
            if not any(ln["video"] == video and abs(ln["start"] - sec) <= LINE_SLACK for ln in m.lines):
                out.append(_finding("high", quote, f"{clock(sec)} 對不到這頁逐字稿任何一句的開頭。", "改成講到這件事那一行開頭的 t 值。"))
        elif not any(r["video"] == video and r["start"] - PAD <= sec <= r["end"] + PAD for r in m.ranges):
            out.append(_finding("high", quote, f"{clock(sec)} 不在這頁出現在影片上的時間範圍內。", "改成這頁出現的時間範圍內。"))
        if label != clock(sec):
            out.append(_finding("low", quote, f"標籤 {label} 和 t={round(sec)}（{clock(sec)}）不一致。", f"標籤改成 {clock(sec)}。"))
    return out


def check(body: str, m: Material) -> list[dict]:
    out = []
    for w in BANNED:
        for hit in re.finditer(re.escape(w), body):
            out.append(_finding("medium", _context(body, hit.start(), hit.end()), f"套話「{w}」。", "刪掉，直接講內容。"))
    for hit in NOT_ONLY.finditer(body):
        out.append(_finding("medium", hit.group(0), "「不僅…更…」句型。", "改成直述句，講清楚因果。"))
    for hit in FIRST_THEN.finditer(body):
        out.append(_finding("low", _context(body, hit.start(), hit.start() + 2), "「首先…其次…」湊結構。", "內容是步驟就用編號清單，不是就寫成連貫的段落。"))
    for bad, good in MAINLAND.items():
        for hit in re.finditer(bad, body):
            out.append(_finding("medium", _context(body, hit.start(), hit.end()), f"大陸用語「{bad}」。", f"改成「{good}」。"))
    for hit in EMOJI.finditer(body):
        out.append(_finding("medium", _context(body, hit.start(), hit.end()), "使用 emoji 或裝飾符號。", "刪掉。"))
    bolds = BOLD.findall(body)
    if len(bolds) > MAX_BOLD:
        out.append(_finding("medium", "、".join(bolds[:6]), f"粗體 {len(bolds)} 處，超過 {MAX_BOLD} 處。", "只留關鍵名詞第一次出現時的粗體。"))
    for hit in QUESTION_HEADING.finditer(body):
        out.append(_finding("low", hit.group(0).strip(), "問句當標題。", "改成描述性的短標題，或拿掉標題。"))
    return out + check_links(body, m)
