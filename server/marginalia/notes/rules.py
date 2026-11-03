"""Model-free checks from style.md (format v2): banned phrases, emoji, bold that covers whole sentences, highlight
and alert syntax, mermaid blocks that will not render, image paths, timestamp links. Prose checks skip code."""

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
BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
BOLD_CHARS = 30  # longer than a term or short phrase: a sentence in bold
HIGHLIGHT = re.compile(r"==([^=\n]+)==")
MAX_HIGHLIGHTS = 5
HIGHLIGHT_CHARS = 80
ALERT = re.compile(r"^>\s*\[!(\w+)\]", re.MULTILINE)
ALERTS = ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION")
FENCED = re.compile(r"^```[^\n]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]+`")
MERMAID = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
DIAGRAMS = ("flowchart", "sequenceDiagram", "stateDiagram-v2", "classDiagram", "block-beta")
UNQUOTED_PAREN_LABEL = re.compile(r"\w\[(?!\")[^\]\n]*[()][^\]\n]*\]")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]*)[^)]*\)")
REF_IMAGE = re.compile(r"!\[[^\]]*\](?!\()")  # ![alt][ref] / ![ref]: destinations live elsewhere, not supported
HTML_IMAGE = re.compile(r"<img\b", re.IGNORECASE)
MAX_RULE_FINDINGS = 40
IMAGE_PATH = re.compile(r"assets/([\w.-]+\.(?:png|jpe?g|webp|svg))")
QUESTION_HEADING = re.compile(r"^#+\s.*[?？]\s*$", re.MULTILINE)
LINK = re.compile(r"\[([^\]\n]*)\]\(video:([^)\s?]*)\?t=([^)\s]*)\)")
SECONDS = re.compile(r"\d{1,6}(?:\.\d+)?")
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
        if m.untaught:
            out.append(_finding("high", quote, "課堂未講解頁不能有影片時間點連結。", "移除連結，只依投影片整理。"))
            continue
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


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def prose(body: str) -> str:
    """The body with code blocks and inline code blanked out, same length so offsets still point into `body`."""
    return INLINE_CODE.sub(_blank, FENCED.sub(_blank, body))


def _brackets_balanced(src: str) -> bool:
    src = re.sub(r'"[^"\n]*"', "", src)  # quoted labels may hold anything
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for ch in src:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs and (not stack or stack.pop() != pairs[ch]):
            return False
    return not stack


def check_mermaid(body: str) -> list[dict]:
    out = []
    if body.count("```") % 2:
        out.append(_finding("medium", "```", "程式碼區塊（```）沒有關閉。", "補上結尾的 ```。"))
    for block in MERMAID.finditer(body):
        src = block.group(1)
        lines = [ln.strip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
        head = lines[0] if lines else ""
        quote = head[:60] or "```mermaid"
        if head.split(" ")[0] not in DIAGRAMS:
            out.append(_finding("high", quote, f"mermaid 圖類型「{head.split(' ')[0]}」不支援，圖會壞掉。", f"第一行改成 {'、'.join(DIAGRAMS)} 其中之一。"))
            continue
        syntax = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("%%"))  # comments hold anything
        if not _brackets_balanced(syntax):
            out.append(_finding("high", quote, "mermaid 圖的括號沒有配對，圖會壞掉。", "檢查每個節點的 [ ]、( )、{ } 是否成對。"))
        if head.startswith("flowchart"):
            for hit in UNQUOTED_PAREN_LABEL.finditer(syntax):
                out.append(_finding("high", hit.group(0), "節點文字裡有括號卻沒加引號，mermaid 會解析失敗。", '節點文字用雙引號包起來，例如 A["CPU (中央處理器)"]。'))
    return out


def _asset_ok(m: Material, name: str) -> bool:
    """The file sits directly in this deck's assets folder: no symlink, nothing resolving outside it."""
    path = m.assets / name
    folder = m.assets.parent.resolve() / "assets"  # where assets must really be, even if `assets` itself is a link
    return not path.is_symlink() and path.resolve().parent == folder and path.is_file()


def check_images(text: str, body: str, m: Material) -> list[dict]:
    """Images in the prose (`text`, code blanked out), quoting from `body`."""
    out = []
    for hit in IMAGE.finditer(text):
        quote = body[hit.start() : hit.end()][:80]
        path = IMAGE_PATH.fullmatch(hit.group(1))
        if not path:
            out.append(_finding("high", quote, "圖片路徑必須是 assets/<檔名>.png|jpg|webp|svg。", "把圖放進這份簡報的 notes/<deck>/assets/，用相對路徑引用。"))
        elif not _asset_ok(m, path.group(1)):
            out.append(_finding("high", quote, f"圖片 {hit.group(1)} 不存在，或不是 assets/ 裡的一般檔案。", "放上圖檔（不要用連結），或拿掉這張圖改用 mermaid。"))
    for hit in REF_IMAGE.finditer(text):
        out.append(_finding("high", body[hit.start() : hit.end()][:80], "不支援參照式圖片。", "改成 ![說明](assets/<檔名>.svg)。"))
    for hit in HTML_IMAGE.finditer(text):
        out.append(_finding("high", body[hit.start() : hit.start() + 60], "不允許用 HTML 放圖片。", "改成 ![說明](assets/<檔名>.svg)。"))
    return out


def check_marks(text: str, body: str) -> list[dict]:
    """Bold, highlight and alert syntax on the prose (`text`), quoting from `body`."""
    out = []
    for hit in BOLD.finditer(text):
        inner = hit.group(1)
        if len(inner) > BOLD_CHARS or re.search(r"[。！？；]", inner):
            out.append(_finding("medium", hit.group(0)[:60], "整句或整段粗體。", "粗體只框名詞或短語；要強調整句用 ==highlight==。"))
    highlights = HIGHLIGHT.findall(text)
    if text.count("==") % 2:
        out.append(_finding("medium", "==", "==highlight== 沒有配對。", "每個 == 都要有對應的結尾 ==。"))
    if len(highlights) > MAX_HIGHLIGHTS:
        out.append(_finding("low", "、".join(h[:12] for h in highlights[:6]), f"highlight {len(highlights)} 處，超過 {MAX_HIGHLIGHTS} 處。", "只留真正要記住的 2–5 句。"))
    for h in highlights:
        if len(h) > HIGHLIGHT_CHARS:
            out.append(_finding("low", h[:40], "highlight 整段。", "只標要記住的那一句。"))
    for hit in ALERT.finditer(text):
        if hit.group(1) not in ALERTS:
            out.append(_finding("medium", hit.group(0), f"提示框類型 [!{hit.group(1)}] 不合法。", f"改成 {'、'.join(ALERTS)} 其中之一。"))
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if not first.startswith("> [!IMPORTANT]"):
        out.append(_finding("low", first[:40], "開頭不是 > [!IMPORTANT] 結論。", "第一個區塊用 > [!IMPORTANT] 一到兩句講這頁的結論。"))
    return out


def check(body: str, m: Material) -> list[dict]:
    text = prose(body)
    out = []
    for w in BANNED:
        for hit in re.finditer(re.escape(w), text):
            out.append(_finding("medium", _context(body, hit.start(), hit.end()), f"套話「{w}」。", "刪掉，直接講內容。"))
    for hit in NOT_ONLY.finditer(text):
        out.append(_finding("medium", hit.group(0), "「不僅…更…」句型。", "改成直述句，講清楚因果。"))
    for hit in FIRST_THEN.finditer(text):
        out.append(_finding("low", _context(body, hit.start(), hit.start() + 2), "「首先…其次…」湊結構。", "內容是步驟就用編號清單，不是就寫成連貫的段落。"))
    for bad, good in MAINLAND.items():
        for hit in re.finditer(bad, text):
            out.append(_finding("medium", _context(body, hit.start(), hit.end()), f"大陸用語「{bad}」。", f"改成「{good}」。"))
    for hit in EMOJI.finditer(text):
        out.append(_finding("medium", _context(body, hit.start(), hit.end()), "使用 emoji 或裝飾符號。", "刪掉。"))
    for hit in QUESTION_HEADING.finditer(text):
        out.append(_finding("low", hit.group(0).strip(), "問句當標題。", "改成描述性的短標題，或拿掉標題。"))
    out += check_marks(text, body) + check_mermaid(body) + check_images(text, body, m) + check_links(body, m)
    return _dedupe(out)[:MAX_RULE_FINDINGS]


def _dedupe(findings: list[dict]) -> list[dict]:
    """One finding per problem and quote, most severe first; a note repeating one mistake 1,000 times gives one row
    per distinct spot and the list stays bounded."""
    seen, out = set(), []
    for f in sorted(findings, key=lambda f: ("high", "medium", "low").index(f["severity"])):
        if (f["problem"], f["quote"]) not in seen:
            seen.add((f["problem"], f["quote"]))
            out.append(f)
    return out
