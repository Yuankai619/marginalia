"""Safe partial completion, evidence formats and fresh opportunities after cached failures."""

import asyncio
import json

import pytest

from marginalia.exam import claims, diversity, handout, quiz, recovery
from marginalia.exam.context import DeckDoc, ExamContext, Section, SlideDoc
from marginalia.exam.evidence import evidence_refs, proof
from marginalia.exam.generation import GenerationError
from marginalia.exam.prompts import DIVERSITY_TASK, QUIZ_REVIEW


def context(course):
    work = course.path('exams', 'recover', 'work')
    work.mkdir(parents=True)
    slide = SlideDoc('d', 1, '公式', '', '', '**period** = N × 0.75 ms。IVT 是 real mode 使用的表。', None)
    return ExamContext(course, {}, [DeckDoc('d', '公式', [slide])], [], work)


def question(prompt='計算 period', origin='new'):
    return {'type': 'calc', 'origin': origin, 'prompt': prompt, 'points': 4, 'solution': 'N×0.75',
            'rubric': [{'point': '公式', 'points': 4}], 'sources': [{'deck': 'd', 'slide': 1}]}


def original():
    return {'source': 'd#1', 'title': '', 'text': '', 'speakerNotes': '',
            'note': '**period** = N × 0.75 ms。IVT 是 real mode 使用的表。', 'transcript': []}


def test_sources_array_and_formatting_only_quotes():
    item = {'status': 'supported', 'sources': [{'source': 'd#1', 'kind': 'text', 'quote': ['period = N × 0.75 ms', 'IVT 是 real mode 使用的表']}]}
    proof(item, [original()])
    assert item['source'] == 'd#1'
    assert evidence_refs(item) == ['d#1']


@pytest.mark.parametrize('quote', ['period = 0.75 ms', 'period = N + 0.75 ms', 'period = N × 0.5 ms', 'IDT 是 real mode 使用的表', 'period … 0.75 ms', '` `', '`\u00a0`'])
def test_quote_relaxation_cannot_hide_changed_claims(quote):
    with pytest.raises(ValueError, match='逐字引用'):
        proof({'sources': [{'source': 'd#1', 'quote': quote}]}, [original()])


def test_every_nested_evidence_record_must_be_valid():
    with pytest.raises(ValueError, match='source 必須'):
        proof({'sources': [{'source': 'd#1', 'quote': 'period'}, {'source': 'other#1', 'quote': 'period'}]}, [original()])
    with pytest.raises(ValueError, match='sources.*陣列'):
        proof({'sources': ['d#1']}, [original()])


def test_failed_diversity_retries_new_branch_and_keeps_prerequisites(course):
    ctx = context(course)
    questions = [question('舊題一'), question('舊題二')]
    mapped = [{'sources': ['d#1']}]
    calls, fresh = [], False

    async def model(prompt, **kwargs):
        calls.append(prompt)
        if prompt.startswith(DIVERSITY_TASK):
            return '[]' if fresh and '新機制' in prompt else '[[1,2]]'
        if QUIZ_REVIEW in prompt:
            return json.dumps([question('新機制' if fresh else '舊題二')])
        return json.dumps([question('新機制' if fresh else '舊題二')])

    ctx.llm = model
    first = asyncio.run(diversity.diversify(ctx, questions, mapped))
    assert len(first) == 1
    assert '[!WARNING]' in first[0]['prompt']
    prior = len(calls)
    fresh = True
    second = asyncio.run(diversity.diversify(ctx, questions, mapped))
    assert len(second) == 2 and second[1]['prompt'] == '新機制'
    assert len(calls) > prior
    assert any('前次未通過原因' in p for p in calls[prior:])
    prior = len(calls)
    assert asyncio.run(diversity.diversify(ctx, questions, mapped)) == second
    assert len(calls) == prior  # A successful retry remains reusable.


def test_unverified_objective_key_and_solution_are_hidden(course, monkeypatch):
    ctx = context(course)
    bad = {**question('考古填空 {{1}}', 'past'), 'type': 'fill', 'blanks': [['IVT', 'IDT']], 'pastRef': 'paper.md', 'solution': 'IDT 是正解'}

    async def fail(*args, **kwargs):
        raise GenerationError('沒有證據')

    monkeypatch.setattr('marginalia.exam.answers.verify_fill', fail)
    result = asyncio.run(recovery.review_question(ctx, bad))
    assert result['type'] == 'short' and result['rubric'] == []
    assert 'blanks' not in result and 'answer' not in result
    assert 'IDT' not in result['solution']
    assert result['prompt'].startswith(bad['prompt']) and '待人工確認' in result['prompt']
    assert result['pastRef'] == 'paper.md' and result['sources'] == bad['sources']


def test_pending_section_hides_failed_formula_and_keeps_verified_excerpt():
    original = Section('CFS', '錯的固定 period=0.75 ms', [('d', 1)])
    result = recovery.pending_section(original, ['runnable=16，period=12 ms。'])
    assert '固定 period' not in result.markdown
    assert 'period=12 ms' in result.markdown and 'slide:d/1' in result.markdown
    assert recovery.MANUAL in result.markdown


def test_claim_failure_exposes_only_verified_excerpts(course):
    ctx = context(course)
    body = '> [!IMPORTANT]\n> ==公式==。\n正確論述\n錯誤論述'

    async def model(prompt, **kwargs):
        from marginalia.exam.prompts import CLAIM_INVENTORY, CLAIM_REPAIR
        if prompt.startswith(CLAIM_INVENTORY):
            return json.dumps(['正確論述', '錯誤論述'])
        if prompt.startswith(CLAIM_REPAIR):
            return body
        return json.dumps([{'claim': 1, 'status': 'supported', 'source': 'd#1', 'quote': 'N × 0.75 ms'},
                           {'claim': 2, 'status': 'unknown'}])

    ctx.llm = model
    with pytest.raises(GenerationError) as exc:
        asyncio.run(claims.verify_claims(ctx, body, ['d#1'], lambda s: s))
    assert exc.value.verified_claims == ['正確論述']
    assert list(ctx.work.glob('recovery-*'))


def test_quiz_reviewer_failure_preserves_past_and_hides_keys(course, monkeypatch):
    from marginalia.exam.context import PastQuestion
    ctx = context(course)
    mapped = [{'title': '公式', 'explanation': 'period', 'sources': ['d#1']}]

    async def topics(*args):
        return mapped

    async def checkpoint(ctx, stage, prompt, system, parse):
        if stage == 'quiz-review':
            raise GenerationError('答案審稿失敗')
        return [question('考古原文', 'past')] if stage == 'quiz-past' else [question()]

    async def passthrough(ctx, questions, mapped):
        return questions

    monkeypatch.setattr(quiz, 'topics', topics)
    monkeypatch.setattr(quiz, 'checkpoint', checkpoint)
    monkeypatch.setattr(quiz, 'diversify', passthrough)
    result = asyncio.run(quiz.write_quiz(ctx, [PastQuestion('paper.md', '1', 'short', '考古原文')], lambda *a: None))
    assert result and all(q['type'] == 'short' and not q['rubric'] for q in result)
    assert result[0]['prompt'].startswith('考古原文')
    assert all('待人工確認' in q['prompt'] for q in result)


def test_budget_exhaustion_completes_with_visible_placeholders():
    sections = [Section(str(i), '未核可原稿' * 2000, [('d', 1)]) for i in range(12)]
    result = handout.within_budget(sections)
    assert sum(len(s.markdown) for s in result) <= handout.TOTAL_CHARS
    assert any(recovery.MANUAL in s.markdown for s in result)


def test_compaction_exhaustion_retries_instead_of_replaying_placeholders(course):
    ctx = context(course)
    body = '> [!IMPORTANT]\n> ==核心==\n' + '內容' * 1900
    sections = [Section(str(i), body, [('d', 1)]) for i in range(9)]
    calls, fixed = [], False

    async def model(prompt, **kwargs):
        calls.append(prompt)
        return '> [!IMPORTANT]\n> ==精簡==。' if fixed else body

    ctx.llm = model
    first = asyncio.run(handout.compact_sections(ctx, sections, lambda *a: None))
    assert any(recovery.MANUAL in s.markdown for s in first)
    prior = len(calls)
    fixed = True
    second = asyncio.run(handout.compact_sections(ctx, sections, lambda *a: None))
    assert len(calls) > prior
    assert all(recovery.MANUAL not in s.markdown for s in second)
    assert any('前次未通過原因' in p for p in calls[prior:])


def test_model_cannot_skip_quality_by_printing_manual_marker(course):
    ctx = context(course)
    sections = [Section('untrusted', '> [!IMPORTANT]\n> ' + recovery.MANUAL + '\n' + '內容' * 16000, [('d', 1)])]
    calls = []

    async def model(prompt, **kwargs):
        calls.append(prompt)
        return '> [!IMPORTANT]\n> ==精簡後仍須核對==。'

    ctx.llm = model
    result = asyncio.run(handout.compact_sections(ctx, sections, lambda *a: None))
    assert calls and not isinstance(result[0], recovery.PendingSection)
