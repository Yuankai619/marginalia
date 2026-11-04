"""Recoverable quality stages and visible, non-gradable manual-review fallbacks."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import asdict

from ..store import _directory_fd, atomic_output
from .context import ExamContext, Section
from .generation import VERSION, GenerationError, data

MANUAL = '==本節待人工確認=='


class PendingSection(Section):
    """Internal provenance: model text cannot declare itself already handled."""


class Recovery:
    """Only a failed/degraded branch rotates its seed; successful prerequisite caches stay usable."""

    def __init__(self, ctx: ExamContext, stage: str, inputs):
        self.ctx = ctx
        key = hashlib.sha256(data([VERSION, stage, asdict(ctx.engine), inputs]).encode()).hexdigest()
        self.path = ctx.work / f'recovery-{key}.json'
        self.seed = ''
        self.reason = ''
        try:
            with _directory_fd(ctx.work, create=False) as directory:
                fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(fd, encoding='utf-8') as saved:
                    raw = json.load(saved)
            if isinstance(raw, dict) and isinstance(raw.get('seed'), str) and isinstance(raw.get('reason'), str):
                self.seed, self.reason = raw['seed'][:64], raw['reason'][:800]
        except (FileNotFoundError, ValueError, TypeError):
            pass

    @property
    def prompt(self) -> str:
        if not self.seed:
            return ''
        return f'\n替代方案種子：{self.seed}\n前次未通過原因 JSON：{data(self.reason)}\n改用新的替換／修復方案，勿重複前次失敗。'

    def failed(self, reason: str) -> None:
        with atomic_output(self.path, root=self.ctx.work) as output:
            output.write(data({'seed': secrets.token_hex(16), 'reason': reason[:800]}).encode())


def manual_question(question: dict, message: str) -> dict:
    """Never publish an unverified key as an objective question or as a reference solution."""
    options = '\n'.join(f"- ({o['id']}) {o['text']}" for o in question.get('options', []))
    prompt = question['prompt'] + ('\n\n' + options if options else '')
    prompt += f'\n\n> [!WARNING]\n> 此題待人工確認：{message} 請先對照來源，不提供自動判分答案。'
    return {k: v for k, v in {**question, 'type': 'short', 'prompt': prompt,
            'solution': '> [!WARNING]\n> 參考答案待人工確認；原未核可答案已隱藏。', 'rubric': []}.items()
            if k not in {'answer', 'blanks', 'options', 'multiple'}}


async def review_question(ctx: ExamContext, question: dict) -> dict:
    from .answers import verify_fill

    try:
        return await verify_fill(ctx, question)
    except GenerationError:
        return manual_question(question, '答案或詳解未完成核對。')


def pending_section(section: Section, verified=()) -> Section:
    body = f'> [!IMPORTANT]\n> {MANUAL}。\n\n> [!WARNING]\n> 本節尚有機制／公式未完成核對，未核可內容已隱藏。以下僅保留已核對節錄，請搭配原投影片人工確認。'
    used = 0
    for claim in dict.fromkeys(verified):
        if used + len(claim) > 2500:
            break
        body += '\n\n' + claim
        used += len(claim)
    body += '\n\n## 原投影片\n\n' + '\n\n'.join(f'![原投影片 {d} 第 {i} 頁](slide:{d}/{i})' for d, i in section.sources[:3])
    return PendingSection(section.title, body, section.sources)
