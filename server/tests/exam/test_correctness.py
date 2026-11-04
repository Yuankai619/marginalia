"""Counterexamples for incorrect aliases, lost correction tails and repeated solution steps."""

from __future__ import annotations

import asyncio
import json

import pytest

from marginalia.exam import (
    answers,
    claims,
    diversity,
    generation,
    handout,
    study,
)
from marginalia.exam.context import DeckDoc, ExamContext, SlideDoc
from marginalia.exam.grade import objective
from marginalia.exam.prompts import (
    ANSWER_SYSTEM,
    CLAIM_INVENTORY,
    CLAIM_REPAIR,
    CLAIM_TASK,
    DIVERSITY_TASK,
    FILL_SOLUTION_REVIEW,
    FILL_SOLUTION_TASK,
    QUIZ_REVIEW,
)


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def field(prompt, name):
    return json.JSONDecoder().raw_decode(prompt.split(name, 1)[1].lstrip())[0]


def ctx_for(course, note):
    work = course.path('exams', 'checks', 'work')
    work.mkdir(parents=True)
    slide = SlideDoc('d', 1, '機制', '', '', note, None)
    return ExamContext(course, {}, [DeckDoc('d', '機制', [slide])], [], work)


def ivt_question():
    return {'id': 'q10', 'type': 'fill', 'origin': 'new', 'points': 4,
            'prompt': 'x86 real mode：用 {{1}} × 4 查 {{2}}，ISR 分 {{3}} 與 {{4}}。',
            'blanks': [['IVN'], ['IVT', 'Interrupt Vector Table', 'IDT', 'Interrupt Descriptor Table'], ['top half'], ['bottom half']],
            'solution': 'IVT，現代 protected mode 使用 IDT。', 'sources': [{'deck': 'd', 'slide': 1}]}


@pytest.mark.parametrize('bad', ['IDT', 'Interrupt Descriptor Table'])
def test_related_wrong_term_is_not_an_accepted_variant(course, bad):
    note = 'IVT：real mode 每格 4 bytes。IDT：protected/64-bit mode 每格 8/16 bytes。IVN 是 vector number，ISR 分 top half 與 bottom half。'
    ctx = ctx_for(course, note)
    seen = []

    async def model(prompt, **kwargs):
        seen.append(prompt)
        if prompt.startswith(FILL_SOLUTION_TASK):
            return encode({'solution': '本題 real mode：IVN、IVT、top half、bottom half，IDT 不適用。'})
        if prompt.startswith(FILL_SOLUTION_REVIEW):
            solution = field(prompt, '修訂詳解 JSON：')
            return encode([{'blank': i + 1, 'aligned': True, 'explanationQuote': solution,
                            'source': 'd#1', 'quote': note} for i in range(4)])
        q = field(prompt, '題目 JSON：')
        checks = [{'blank': i + 1, 'answer': a, 'status': 'wrong' if a in ('IDT', 'Interrupt Descriptor Table') else 'equivalent',
                   'source': 'd#1', 'quote': note, 'reason': '本題限定 real mode 4-byte entries，不能更換模式'}
                  for i, accepted in enumerate(q['blanks']) for a in accepted]
        near = [{'blank': i + 1, 'answer': a, 'source': 'd#1', 'quote': note, 'reason': '同條件下不同名詞'}
                for i, a in enumerate(['IRQ', 'IDT', 'bottom half', 'top half'])]
        return encode({'variants': checks, 'nearMisses': near})

    ctx.llm = model
    fixed = asyncio.run(answers.verify_fill(ctx, ivt_question()))
    assert fixed['blanks'][1] == ['IVT', 'Interrupt Vector Table']
    assert 'IDT 不適用' in fixed['solution']
    assert any(p.startswith(FILL_SOLUTION_REVIEW) for p in seen)
    assert objective(fixed, ['IVN', bad, 'top half', 'bottom half']) == {'status': 'partial', 'score': 3.0, 'maxScore': 4}
    assert objective(fixed, ['IVN', 'IVT', 'top half', 'bottom half'])['score'] == 4
    assert note in field(seen[0], '完整來源 JSON：')[0]['note']


def test_unverified_variants_and_fabricated_evidence_fail_closed(course):
    ctx = ctx_for(course, 'real mode IVT 的 entry 為 4 bytes。')
    q = ivt_question()

    async def missing(prompt, **kwargs):
        return encode({'variants': [], 'nearMisses': []})

    ctx.llm = missing
    with pytest.raises(generation.GenerationError, match='逐項核對'):
        asyncio.run(answers.verify_fill(ctx, q))

    async def fabricated(prompt, **kwargs):
        checks = [{'blank': i + 1, 'answer': a, 'status': 'equivalent', 'source': 'd#1', 'quote': '這個引文不存在', 'reason': '假證據'}
                  for i, accepted in enumerate(q['blanks']) for a in accepted]
        return encode({'variants': checks, 'nearMisses': []})

    ctx.llm = fabricated
    with pytest.raises(generation.GenerationError, match='逐字引用'):
        asyncio.run(answers.verify_fill(ctx, q))


@pytest.mark.parametrize('runnable', [9, 16, 32])
def test_formula_conflict_reads_full_tail_and_keeps_process_factor(course, runnable):
    correction = '## 補充\n超過 8 個 runnable 時，period = process 數 × 0.75 ms。每個等權重 process 的 slice 為 0.75 ms。'
    note = '早期 CFS period 的門檻是 8。\n' + '長篇解釋。' * 1600 + '\n' + correction
    ctx = ctx_for(course, note)
    old = '> [!IMPORTANT]\n> ==CFS==。\nprocess 超過 8 個時 period 為固定 0.75 ms。'
    period = runnable * .75
    corrected_claim = f'runnable={runnable}：period={runnable}×0.75={period:g} ms，等權重 slice={period:g}/{runnable}=0.75 ms。'
    fixed = '> [!IMPORTANT]\n> ==CFS==。\n' + corrected_claim
    seen = []

    async def model(prompt, **kwargs):
        seen.append(prompt)
        if prompt.startswith(CLAIM_INVENTORY):
            body = field(prompt, '正文 JSON：')
            return encode([corrected_claim if corrected_claim in body else 'process 超過 8 個時 period 為固定 0.75 ms。'])
        if prompt.startswith(CLAIM_TASK):
            full = field(prompt, '完整來源 JSON：')[0]['note']
            assert full == note  # The actual evidence pass must see every character, not just the excerpt.
            claim = field(prompt, 'claim JSON：')[0]
            status = 'supported' if claim == corrected_claim else 'conflict'
            return encode([{'claim': 1, 'status': status, 'source': 'd#1', 'quote': correction,
                            'correction': corrected_claim, 'counterexample': f'N={runnable} gives period={period:g} ms'}])
        assert prompt.startswith(CLAIM_REPAIR)
        assert field(prompt, '回查完整來源 JSON：')[0]['note'] == note
        return fixed

    ctx.llm = model
    assert correction in study.material(ctx, ['d#1'], budget=200)[0]['note']
    result = asyncio.run(claims.verify_claims(ctx, old, ['d#1'], lambda r: handout.section_body(r, 6000)))
    assert corrected_claim in result
    assert '固定 0.75' not in result
    assert period / runnable == .75
    assert sum(p.startswith(CLAIM_TASK) for p in seen) == 2  # Corrected output is independently checked again.


def test_validation_version_invalidates_old_checkpoint(course, monkeypatch):
    ctx = ctx_for(course, '來源')
    calls = []

    async def model(*args, **kwargs):
        calls.append(1)
        return encode({'old': len(calls) == 1})

    ctx.llm = model
    monkeypatch.setattr(generation, 'VERSION', 1)
    assert asyncio.run(generation.checkpoint(ctx, 'quiz-review', 'same prompt', 'same system', json.loads))['old']
    monkeypatch.setattr(generation, 'VERSION', 2)
    assert not asyncio.run(generation.checkpoint(ctx, 'quiz-review', 'same prompt', 'same system', json.loads))['old']
    assert len(calls) == 2
    asyncio.run(generation.checkpoint(ctx, 'quiz-review', 'same prompt', 'same system', json.loads))
    assert len(calls) == 2


def calc(prompt, solution):
    return {'type': 'calc', 'origin': 'new', 'prompt': prompt, 'points': 4, 'solution': solution,
            'rubric': [{'point': '解題過程', 'points': 4}], 'sources': [{'deck': 'd', 'slide': 1}]}


def test_whole_quiz_replaces_same_steps_with_different_mechanism(course):
    ctx = ctx_for(course, '可考 cache miss 成本或 TLB miss 與 page fault 的差異。')
    q8 = calc('1000 cache lines，direct 5 us，80 ns memory，1 ns cache，10 ms timeslice，算 overhead。', '算 miss 額外成本、加 direct、算 overhead、解釋間接成本。')
    q13 = calc('5000 cache lines，direct 5 us，80 ns memory，1 ns cache，10 ms timeslice，算 overhead。', '算 miss 額外成本、加 direct、算 overhead、解釋間接成本。')
    replacement = calc('page size=1 KiB，VA=2500，page 2 對應 frame 3，求 PA。', 'page=2，offset=452，PA=3524 B。')
    checked = []

    async def model(prompt, **kwargs):
        if prompt.startswith(DIVERSITY_TASK):
            whole = field(prompt, '整卷 JSON：')
            checked.append(whole)
            return encode([[1, 2]] if '5000 cache' in whole[1]['prompt'] else [])
        if QUIZ_REVIEW in prompt:
            return encode(field(prompt, '草稿 JSON：'))
        return encode([replacement])

    ctx.llm = model
    result = asyncio.run(diversity.diversify(ctx, [q8, q13], [{'sources': ['d#1']}]))
    assert result[0] == q8
    assert result[1]['prompt'] == replacement['prompt']
    assert len(checked) == 2
    assert len(result) == 2


def test_claim_evidence_is_bounded_without_losing_late_claims(course):
    note = '完整來源。'
    ctx = ctx_for(course, note)
    statements = [f'機制{i}。' for i in range(17)]
    body = '> [!IMPORTANT]\n> ==機制==。\n' + '\n'.join(statements)
    checked = []

    async def model(prompt, **kwargs):
        if prompt.startswith(CLAIM_INVENTORY):
            return encode(statements)
        selected = field(prompt, 'claim JSON：')
        assert len(selected) <= 8
        checked.extend(selected)
        return encode([{'claim': i + 1, 'status': 'supported', 'source': 'd#1', 'quote': note} for i in range(len(selected))])

    ctx.llm = model
    assert asyncio.run(claims.verify_claims(ctx, body, ['d#1'], lambda s: s)) == body
    assert checked == statements


def test_visual_mechanism_survives_full_source_verification(course):
    ctx = ctx_for(course, '')
    image = ctx.work / 'slide.png'
    image.write_bytes(b'synthetic vision fixture')
    ctx.decks[0].slides[0].image = image
    body = '> [!IMPORTANT]\n> ==CPU 經 MMU 存取 RAM==。'

    async def model(prompt, **kwargs):
        if prompt.startswith(CLAIM_INVENTORY):
            return encode(['CPU 經 MMU 存取 RAM'])
        assert kwargs['images'] == [image]
        return encode([{'claim': 1, 'status': 'supported', 'source': 'd#1', 'kind': 'image',
                        'observation': 'CPU 方框的箭頭經 MMU 方框再到 RAM 方框。'}])

    ctx.llm = model
    assert asyncio.run(claims.verify_claims(ctx, body, ['d#1'], lambda s: s)) == body


def test_late_correction_wins_over_earlier_source_in_another_batch(course):
    old_note = 'period 固定為 .75 ms。' + 'x' * 25000
    ctx = ctx_for(course, old_note)
    corrected = '## 勘誤\nN>8 時 period=N×.75 ms；N=16 時 period=12 ms。'
    ctx.decks[0].slides.append(SlideDoc('d', 2, '勘誤', '', '', corrected, None))
    statement = 'N=16 時 period=12 ms。'
    body = '> [!IMPORTANT]\n> ==CFS==。\n' + statement

    async def model(prompt, **kwargs):
        if prompt.startswith(CLAIM_INVENTORY):
            return encode([statement])
        if prompt.startswith(CLAIM_TASK):
            original = field(prompt, '完整來源 JSON：')[0]
            late = original['source'] == 'd#2'
            return encode([{'claim': 1, 'status': 'supported' if late else 'conflict', 'source': original['source'],
                            'quote': corrected if late else 'period 固定為 .75 ms。', 'correction': 'period=.75 ms', 'counterexample': 'N=16'}])
        assert '回查附帶的所有完整原頁' in prompt
        originals = field(prompt, '回查完整來源 JSON：')
        assert {s['source'] for s in originals} == {'d#1', 'd#2'}
        return encode({'status': 'supported', 'source': 'd#2', 'quote': corrected, 'reason': '後頁明示勘誤優先'})

    ctx.llm = model
    assert asyncio.run(claims.verify_claims(ctx, body, ['d#1', 'd#2'], lambda s: s)) == body


def test_fill_alias_uses_later_correction_instead_of_discarding_it(course):
    old_note = '舊規則不接受 new-mode。' + 'x' * 25000
    ctx = ctx_for(course, old_note)
    correction = '## 勘誤\n本題的新規則只接受 new-mode，old-mode 不適用。'
    ctx.decks[0].slides.append(SlideDoc('d', 2, '勘誤', '', '', correction, None))
    q = {'type': 'fill', 'origin': 'new', 'prompt': '依勘誤後的新規則填 {{1}}。', 'points': 1,
         'blanks': [['new-mode']], 'sources': [{'deck': 'd', 'slide': 1}, {'deck': 'd', 'slide': 2}]}

    async def model(prompt, **kwargs):
        if kwargs.get('system') == ANSWER_SYSTEM:
            original = field(prompt, '完整來源 JSON：')[0]
            late = original['source'] == 'd#2'
            evidence = {'source': original['source'], 'quote': correction if late else '舊規則不接受 new-mode。', 'reason': '新舊條件'}
            return encode({'variants': [{'blank': 1, 'answer': 'new-mode', 'status': 'equivalent' if late else 'wrong', **evidence}],
                           'nearMisses': [{'blank': 1, 'answer': 'old-mode' if late else 'new-mode', **evidence}]})
        return encode({'status': 'supported', 'source': 'd#2', 'quote': correction, 'reason': '以後頁明示勘誤為準'})

    ctx.llm = model
    fixed = asyncio.run(answers.verify_fill(ctx, q))
    assert fixed['blanks'] == [['new-mode']]
    assert objective(fixed, ['new-mode'])['status'] == 'correct'
    assert objective(fixed, ['old-mode'])['score'] == 0


def test_duplicate_replacement_keeps_the_only_covered_deck(course):
    ctx = ctx_for(course, '不同解題機制。')
    ctx.decks.append(DeckDoc('e', '後半課程', [SlideDoc('e', 1, '另一機制', '', '', '不同解題機制。', None)]))
    first = calc('機制甲，數字 1', '相同步驟')
    second = calc('機制甲，數字 2', '相同步驟')
    second['sources'] = [{'deck': 'e', 'slide': 1}]
    attempts = []

    async def model(prompt, **kwargs):
        if prompt.startswith(DIVERSITY_TASK):
            current = field(prompt, '整卷 JSON：')
            return encode([] if current[1]['prompt'] == '機制乙' else [[1, 2]])
        if QUIZ_REVIEW in prompt:
            return encode(field(prompt, '草稿 JSON：'))
        attempts.append(prompt)
        q = calc('機制乙', '不同步驟')
        if len(attempts) > 1:
            q['sources'] = [{'deck': 'e', 'slide': 1}]
        return encode([q])

    ctx.llm = model
    result = asyncio.run(diversity.diversify(ctx, [first, second], [{'sources': ['d#1', 'e#1']}]))
    assert len(attempts) == 2
    assert result[1]['sources'] == [{'deck': 'e', 'slide': 1}]


def test_solution_recheck_rejects_teaching_removed_answer(course):
    note = 'IVT 是 real mode，IDT 是 protected mode。IVN、top half、bottom half。'
    ctx = ctx_for(course, note)

    async def model(prompt, **kwargs):
        if prompt.startswith(FILL_SOLUTION_TASK):
            return encode({'solution': 'real mode 的正解是 IDT。'})
        if prompt.startswith(FILL_SOLUTION_REVIEW):
            return encode([{'blank': i + 1, 'aligned': False} for i in range(4)])
        q = field(prompt, '題目 JSON：')
        return encode({'variants': [{'blank': i + 1, 'answer': a, 'status': 'wrong' if a in ('IDT', 'Interrupt Descriptor Table') else 'equivalent',
                                      'source': 'd#1', 'quote': note, 'reason': '同模式判斷'}
                                     for i, accepted in enumerate(q['blanks']) for a in accepted],
                       'nearMisses': [{'blank': i + 1, 'answer': a, 'source': 'd#1', 'quote': note, 'reason': '不同機制'}
                                     for i, a in enumerate(['IRQ', 'IDT', 'bottom half', 'top half'])]})

    ctx.llm = model
    with pytest.raises(generation.GenerationError, match='詳解與已驗證答案不一致'):
        asyncio.run(answers.verify_fill(ctx, ivt_question()))
