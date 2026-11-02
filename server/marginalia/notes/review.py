"""Fixed reviewer agents for generated notes, then one revision pass.

Three model reviewers read every note against the slide and transcript: correctness, style and coverage. A
model-free rules check (rules.py) runs alongside. Optionally Codex gives a second correctness opinion. Findings go
to `generated/reviews/<deck>/NNN.json`; if any is high or medium the writer model revises the note, and the note
becomes `status: reviewed`. Notes the user edited get findings but are never rewritten unless `force` is set.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from .. import config
from ..llm import claude, codex
from ..store import Course, write_json
from . import notefile, rules
from .batch import Progress, run_slides, select
from .generate import STYLE, meta, parse_output
from .generate import SYSTEM as WRITER_SYSTEM
from .material import Gatherer, Material, render

SEVERITIES = ("high", "medium", "low")
SYSTEM = f"你是作業系統課講義的審稿人。學生會拿這份筆記搭配投影片和上課影片讀。以下是筆記的寫作規範：\n\n{STYLE}"

OUTPUT = """## 輸出格式

只輸出一個 JSON 物件，不要任何其他文字：
{"findings": [{"severity": "high|medium|low", "quote": "…", "problem": "…", "fix": "…"}]}
- severity：high＝內容錯誤或會誤導讀者；medium＝讀者會卡住或明顯違反規範；low＝小修。
- quote：筆記裡有問題的原文，逐字複製，最多 80 字（涵蓋度審稿填逐字稿那一行，含 t=）。
- problem：哪裡有問題，一句話。fix：具體怎麼改，給出改寫後的句子或要補的內容。
- 沒有問題就輸出 {"findings": []}。不要為了湊數挑毛病，也不要重複同一個問題。
- 用繁體中文。"""

REVIEWERS = {
    "correctness": """你是嚴格的助教，負責正確性審稿。對照投影片圖片、投影片文字、講者備註和逐字稿，找出筆記裡的：
1. 事實錯誤，或和老師說法、投影片內容矛盾的地方。
2. 時間點錯誤：每個 [mm:ss](video:…?t=秒) 連結，去逐字稿找 t 附近那幾行，確認老師在那裡真的講到這句話的內容（前後 15 秒內算對）。不對就在 fix 給出正確的秒數。
3. `## 補充` 裡錯誤、不精確或過度簡化到變錯的技術陳述。
4. 正文裡出現老師沒講、投影片也沒有的內容（應該移到補充），或補充寫得像是老師說的。
5. 逐字稿的錯字被照抄進筆記（例如把 page fault 寫成 patch fault）。
不要管文風。""",
    "style": """你是文字編輯，負責文風審稿。照系統提示裡的寫作規範，找出筆記裡的：
1. AI 味：套話、空泛開場或結尾、粗體氾濫、排比湊字、首先其次湊結構、問句標題、沒內容的形容詞。
2. 不清楚的地方：名詞沒解釋就用、因果跳步、一句講太多件事、讀者讀完還是不知道「為什麼」。
3. 用語：非台灣用語、技術名詞中英混用不一致。
4. 結構：沒有先講這頁要解決的問題；補充和正文混在一起；自我檢查考背誦而不是理解。
不要管事實對錯。""",
    "coverage": """你是負責涵蓋度審稿的助教。讀逐字稿，列出老師在這頁講到、對理解這頁有幫助，但筆記漏掉的重點：
老師舉的例子、比喻、數字、特別強調或說會考的地方、常見錯誤的提醒、和其他章節的連結。
閒聊、點名、口頭禪、行政雜事、轉到下一頁的過場話不算。投影片上有、老師也有講、但筆記沒寫的機制也算。
quote 填逐字稿那一行（含 t=），fix 寫要補什麼、補在哪一段、附上的時間點。""",
}

REVISE = """## 任務

上面是第 {index} 頁目前的筆記，和審稿人提出的問題。依照寫作規範修訂這份筆記：
- 成立的問題都要改。審稿人也可能看錯：對照投影片和逐字稿確認，不成立的就不改。
- 沒被指出問題的段落保持原樣，不要整份重寫。
- 只輸出修訂後完整的筆記 markdown 本文：不要 frontmatter、不要用 ``` 包起來、不要說明你改了什麼。"""


def parse_findings(text: str, reviewer: str) -> list[dict]:
    """Pull the findings list out of a reviewer reply, tolerating fences and chatter around the JSON."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"{reviewer} 審稿沒有回傳 JSON")
    data = json.loads(m.group(0))
    out = []
    for f in data.get("findings", []) if isinstance(data, dict) else []:
        if not isinstance(f, dict) or not f.get("problem"):
            continue
        sev = f.get("severity") if f.get("severity") in SEVERITIES else "medium"
        out.append({"reviewer": reviewer, "severity": sev, **{k: str(f.get(k) or "") for k in ("quote", "problem", "fix")}})
    return out


def reviewer_prompt(m: Material, body: str, task: str) -> str:
    return f"{render(m)}\n\n## 要審的筆記（第 {m.index} 頁）\n\n{body}\n\n## 你的審稿任務\n\n{task}\n\n{OUTPUT}"


def findings_text(findings: list[dict]) -> str:
    return "\n".join(
        f"- [{f['severity']}] ({f['reviewer']}) 原文：{f['quote'] or '（無）'}\n  問題：{f['problem']}\n  建議：{f['fix']}"
        for f in findings
    )


class Reviewer:
    """Runs the reviewer agents for one deck, sharing one limit on concurrent model calls."""

    def __init__(self, course: Course, deck_id: str, codex_home: Path | None = None):
        self.course, self.deck_id = course, deck_id
        self.g = Gatherer(course, deck_id)
        self.sem = asyncio.Semaphore(max(1, config.GEN_CONCURRENCY))
        self.codex_home = codex_home if codex_home and codex.available(codex_home) else None

    async def _claude(self, prompt: str, system: str, m: Material, model: str) -> str:
        call = claude.Call(prompt=prompt, system=system, images=m.images, model=model)
        async with self.sem:
            return await claude.complete(call)

    async def _review(self, name: str, m: Material, body: str) -> list[dict]:
        out = await self._claude(reviewer_prompt(m, body, REVIEWERS[name]), SYSTEM, m, config.REVIEW_MODEL)
        return parse_findings(out, name)

    async def _codex(self, m: Material, body: str) -> list[dict]:
        prompt = f"{SYSTEM}\n\n{reviewer_prompt(m, body, REVIEWERS['correctness'])}"
        async with self.sem:
            out = await codex.complete(prompt, codex_home=self.codex_home, images=m.images)
        return parse_findings(out, "codex-correctness")

    async def review_slide(self, index: int, force: bool = False) -> dict | None:
        """Review one note, revise it if needed. Returns the review record, or None when there is nothing to review."""
        path = self.course.note_path(self.deck_id, index)
        note = notefile.read(path)
        if note is None or note[0].get("status") == "skipped":
            return None
        front, body = note
        m = self.g.get(index)

        jobs = {name: self._review(name, m, body) for name in REVIEWERS}
        if self.codex_home:
            jobs["codex-correctness"] = self._codex(m, body)
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        findings = rules.check(body, m)
        errors = {}
        for name, r in zip(jobs, results, strict=True):
            if isinstance(r, BaseException):
                errors[name] = str(r) or type(r).__name__
            else:
                findings.extend(r)
        if all(name in errors for name in REVIEWERS):
            raise RuntimeError(f"第 {index} 頁審稿全部失敗：{next(iter(errors.values()))}")
        findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))

        revised, status = False, "reviewed"
        editable = force or front.get("status", "edited") != "edited"
        if editable and any(f["severity"] != "low" for f in findings):
            prompt = (
                f"{render(m)}\n\n## 目前的筆記\n\n{body}\n\n## 審稿意見\n\n{findings_text(findings)}\n\n"
                f"{REVISE.format(index=index)}"
            )
            new_status, new_body = parse_output(await self._claude(prompt, WRITER_SYSTEM, m, config.WRITER_MODEL))
            if new_body:
                body, revised = new_body, True
                status = "skipped" if new_status == "skipped" else status

        record = {"findings": findings, "revised": revised, "reviewedAt": notefile.now()}
        if errors:
            record["errors"] = errors
        write_json(self.course.review_path(self.deck_id, index), record)
        if editable:
            notefile.write_unless_edited(path, {**front, **meta(m, status)}, body, force)
        return record


async def areview_deck(
    course: Course,
    deck_id: str,
    progress: Progress | None = None,
    slides: list[int] | None = None,
    force: bool = False,
    codex_home: Path | None = None,
) -> dict:
    progress = progress or (lambda f, msg: None)
    rv = Reviewer(course, deck_id, codex_home)
    # resuming reviews generated notes; listed slides are reviewed again (edited ones get findings, not rewrites)
    todo = select(
        course, deck_id, len(rv.g.slides), slides,
        lambda s: s == "generated" or (s in ("reviewed", "edited") and (slides is not None or force)),
    )  # fmt: skip
    if not todo:
        progress(1.0, "沒有需要審稿的筆記")
        return {"reviewed": [], "revised": []}
    progress(0.0, f"審稿 {len(todo)} 頁（{'Claude＋Codex' if rv.codex_home else 'Claude'}）")
    records = await run_slides(todo, lambda i: rv.review_slide(i, force), "審稿", progress)
    return {
        "reviewed": [i for i, r in records.items() if r is not None],
        "revised": [i for i, r in records.items() if r and r["revised"]],
    }


def review_deck(
    course: Course,
    deck_id: str,
    progress: Progress | None = None,
    slides: list[int] | None = None,
    force: bool = False,
    codex_home: Path | None = None,
) -> dict:
    """Blocking wrapper for job threads. Returns {reviewed:[i], revised:[i]}. `codex_home` adds Codex as a second
    correctness reviewer when it is logged in there; otherwise Codex is skipped. Raises if any slide failed, after
    the others are done."""
    return asyncio.run(areview_deck(course, deck_id, progress, slides, force, codex_home))
