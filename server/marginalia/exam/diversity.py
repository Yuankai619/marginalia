"""Compare complete quizzes by concept/solution steps, then replace redundant new slots."""

from __future__ import annotations

from .context import ExamContext
from .generation import GenerationError, checkpoint, data
from .prompts import DIVERSITY_TASK, QUIZ_REVIEW, QUIZ_SYSTEM
from .recovery import Recovery, manual_question, review_question
from .schema import json_reply
from .study import material


async def diversify(ctx: ExamContext, questions: list[dict], mapped: list[dict]) -> list[dict]:
    from .quiz import validate

    recovery = Recovery(ctx, "diversity", [questions, mapped])
    current = questions

    def incomplete(reason, replace=()):
        recovery.failed(reason)
        kept = []
        for i, q in enumerate(current):
            if i not in replace:
                kept.append(q)
                continue
            other_decks = {s["deck"] for j, other in enumerate(current) if j != i and j not in replace for s in other["sources"]}
            if {s["deck"] for s in q["sources"]} - other_decks:
                # Keep scope visible without publishing another copy of a known duplicate.
                kept.append(manual_question({**q, "prompt": "此範圍尚待補上不同解題步驟的新題。"}, "替換題未通過去重。"))
        if kept:
            kept[0] = {**kept[0], "prompt": kept[0]["prompt"] + "\n\n> [!WARNING]\n> 整卷去重尚待人工確認；已剔除未通過的重複新題，部分範圍可能標記待補題。"}
        return kept
    for attempt in range(5):
        count = len(current)

        def parse(reply, count=count):
            groups = json_reply(reply, list)
            for group in groups:
                if (not isinstance(group, list) or len(group) < 2 or len(group) != len(set(group))
                        or any(not isinstance(i, int) or not 1 <= i <= count for i in group)):
                    raise ValueError("重複組必須引用本卷至少兩個不同題序")
            return groups

        try:
            groups = await checkpoint(ctx, "quiz-diversity", f"{DIVERSITY_TASK}\n整卷 JSON：{data(current)}" + recovery.prompt, QUIZ_SYSTEM, parse)
        except GenerationError:
            return incomplete("整卷去重格式修復次數已用完")
        replace = set()
        for group in groups:
            ordered = sorted(group, key=lambda i: (current[i - 1]["origin"] != "past", i))
            replace.update(i - 1 for i in ordered[1:] if current[i - 1]["origin"] == "new")
        if not replace:
            return current
        if attempt == 4:
            return incomplete("整卷仍有語意或解題步驟重複的新題", replace)
        for i in sorted(replace):
            old = current[i]
            other_decks = {s["deck"] for j, q in enumerate(current) if j != i for s in q["sources"]}
            required = {s["deck"] for s in old["sources"]} - other_decks
            refs = list(dict.fromkeys(r for t in mapped for r in t["sources"]))
            prompt = ("替換指定的一題新題；改考本卷尚未涵蓋的機制或解題方法，不可只換數字／名稱。"
                      f"題型保持 {old['type']}，輸出一題 JSON 陣列。\n整卷 JSON：{data(current)}\n"
                      f"替換題序：{i + 1}\n核心主題 JSON：{data(mapped)}\n來源素材 JSON：{data(material(ctx, refs))}")
            if required:
                prompt += f"\n本題必須保留目前唯一涵蓋的簡報 JSON：{data(sorted(required))}"
            prompt += recovery.prompt
            slot = {"type": old["type"], "topic": {"sources": refs}}

            def replacement(reply, slot=slot, required=required):
                result = validate(reply, ctx, [slot], past=False)
                if not required <= {s["deck"] for s in result[0]["sources"]}:
                    raise ValueError("替換題遺漏原本唯一涵蓋的簡報")
                return result
            try:
                raw = await checkpoint(ctx, "quiz-replace", prompt, QUIZ_SYSTEM,
                                       replacement)
                reviewed = await checkpoint(ctx, "quiz-replace-review",
                                        f"{prompt}\n草稿 JSON：{data(raw)}\n{QUIZ_REVIEW}", QUIZ_SYSTEM,
                                        replacement)
            except GenerationError:
                return incomplete("替換新題未完成答案核對", replace)
            current = [*current[:i], await review_question(ctx, reviewed[0]), *current[i + 1:]]
    raise AssertionError("unreachable")
