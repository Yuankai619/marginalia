"""Check every accepted fill variant against the same question conditions."""

from __future__ import annotations

from copy import deepcopy

from .claims import reconcile
from .context import ExamContext
from .evidence import full_material, images_for, proof, source_batches
from .generation import GenerationError, checkpoint, data
from .grade import normalize, objective
from .prompts import (
    ANSWER_SYSTEM,
    ANSWER_TASK,
    FILL_SOLUTION_REVIEW,
    FILL_SOLUTION_TASK,
)
from .schema import json_reply


async def verify_fill(ctx: ExamContext, question: dict) -> dict:
    if question["type"] != "fill":
        return question
    variants = [(i + 1, answer) for i, accepted in enumerate(question["blanks"]) for answer in accepted]
    decisions = {v: [] for v in variants}
    negatives = []
    refs = [f"{s['deck']}#{s['slide']}" for s in question["sources"]]
    for originals in source_batches(ctx, refs):
        images = images_for(ctx, originals)

        def parse(reply, originals=originals, images=images):
            raw = json_reply(reply, dict)
            checks = raw.get("variants")
            if not isinstance(checks, list) or len(checks) != len(variants):
                raise ValueError("每個 accepted variant 都必須逐項核對")
            if any(not isinstance(c, dict) for c in checks):
                raise TypeError("變體核對必須是 JSON 物件")
            for check, (blank, answer) in zip(checks, variants, strict=True):
                if check.get("blank") != blank or check.get("answer") != answer:
                    raise ValueError("變體核對須保留每個空格、答案與順序")
                if check.get("status") not in ("equivalent", "wrong", "unknown") or not check.get("reason"):
                    raise ValueError("變體必須說明同題幹條件下等價、錯誤或無證據的理由")
                if check["status"] != "unknown":
                    proof(check, originals, images)
            near = raw.get("nearMisses")
            if not isinstance(near, list):
                raise TypeError("必須列出相關但錯誤的答案反例")
            if any(not isinstance(c, dict) for c in near):
                raise TypeError("錯答反例必須是 JSON 物件")
            for item in near:
                if (not isinstance(item.get("blank"), int) or not 1 <= item["blank"] <= len(question["blanks"])
                        or not isinstance(item.get("answer"), str) or not item["answer"].strip() or not item.get("reason")):
                    raise ValueError("錯答反例須有有效空格、答案與不等價原因")
                proof(item, originals, images)
            return checks, near

        prompt = f"{ANSWER_TASK}\n題目 JSON：{data(question)}\n完整來源 JSON：{data(originals)}\n附圖順序 JSON：{data(list(images))}"
        checks, near = await checkpoint(ctx, "fill-equivalence", prompt, ANSWER_SYSTEM, parse, list(images.values()))
        for check, variant in zip(checks, variants, strict=True):
            decisions[variant].append(check)
        negatives.extend(near)
    accepted = set()
    for variant, checked in decisions.items():
        blank, answer = variant
        compared = [*checked, *[{**n, "status": "wrong"} for n in negatives
                               if n["blank"] == blank and normalize(n["answer"]) == normalize(answer)]]
        statuses = {c["status"] for c in compared}
        equivalent = "equivalent" in statuses and "wrong" not in statuses
        if "equivalent" in statuses and "wrong" in statuses:
            verdicts = [{**c, "status": {"equivalent": "supported", "wrong": "conflict", "unknown": "unknown"}[c["status"]]}
                        for c in compared if c["status"] != "unknown"]
            disputed_refs = list(dict.fromkeys(v["source"] for v in verdicts))
            decision = await reconcile(ctx, f"第 {blank} 空可接受答案：{answer}", verdicts, disputed_refs, data(question))
            equivalent = decision["status"] == "supported"
        if equivalent:
            accepted.add(variant)
    out = deepcopy(question)
    out["blanks"] = [[a for a in variants if (i + 1, a) in accepted] for i, variants in enumerate(question["blanks"])]
    if not all(out["blanks"]):
        raise GenerationError("填空題沒有在同一條件下獲來源支持的答案，請重寫題幹或答案")
    # Conflicting negative examples have also been adjudicated above. Keep only genuine near misses.
    negatives = [n for n in negatives if normalize(n["answer"]) not in {normalize(a) for a in out["blanks"][n["blank"] - 1]}]
    missing = set(range(1, len(out["blanks"]) + 1)) - {n["blank"] for n in negatives}
    if missing:
        negatives.extend(await counterexamples(ctx, out, refs, missing))
    for negative in negatives:
        i = negative["blank"] - 1
        if normalize(negative["answer"]) in {normalize(a) for a in out["blanks"][i]}:
            raise GenerationError("填空題的相關錯答仍在 accepted variants 中，已停止生成")
        answers = [accepted[0] for accepted in out["blanks"]]
        answers[i] = negative["answer"]
        if objective(out, answers)["status"] == "correct":
            raise GenerationError("填空錯答反例誤判滿分，已停止生成")
    if out["blanks"] != question["blanks"] and out.get("solution"):
        out = await align_solution(ctx, out, refs, question["blanks"])
    return out


async def counterexamples(ctx: ExamContext, question: dict, refs: list[str], missing: set[int]) -> list[dict]:
    originals = full_material(ctx, refs)
    images = images_for(ctx, originals)

    def parse(reply):
        raw = json_reply(reply, list)
        if any(not isinstance(n, dict) for n in raw) or {n.get("blank") for n in raw} != missing:
            raise ValueError("每個缺少反例的空格都必須提供錯答")
        for n in raw:
            if not isinstance(n.get("answer"), str) or not n["answer"].strip() or not n.get("reason"):
                raise ValueError("錯答須有答案與同條件下不成立的理由")
            if normalize(n["answer"]) in {normalize(a) for a in question["blanks"][n["blank"] - 1]}:
                raise ValueError("已裁決等價的答案不能當錯答反例")
            proof(n, originals, images)
        return raw

    prompt = ("為已裁決答案集合補充相關但錯的答案反例，不能把正確變體當反例。只輸出 JSON 陣列："
              '[{"blank":1,"answer":"錯答","source":"deck#1","quote":"逐字證據","reason":"不符合題幹條件"}]。'
              f"\n缺少反例的空格 JSON：{data(sorted(missing))}\n題目 JSON：{data(question)}"
              f"\n完整來源 JSON：{data(originals)}\n附圖順序 JSON：{data(list(images))}")
    return await checkpoint(ctx, "fill-counterexamples", prompt, ANSWER_SYSTEM, parse, list(images.values()))


async def align_solution(ctx: ExamContext, question: dict, refs: list[str], previous: list) -> dict:
    originals = full_material(ctx, refs)
    images = images_for(ctx, originals)
    base = (f"\n題目 JSON：{data(question)}\n原答案集合 JSON：{data(previous)}"
            f"\n完整來源 JSON：{data(originals)}\n附圖順序 JSON：{data(list(images))}")

    def parse(reply):
        result = json_reply(reply, dict).get("solution")
        if not isinstance(result, str) or not result.strip() or len(result) > 8000:
            raise ValueError("修訂詳解須為非空且不超過 8000 字的文字")
        return result.strip()

    solution = await checkpoint(ctx, "fill-solution", FILL_SOLUTION_TASK + base, ANSWER_SYSTEM, parse, list(images.values()))

    def confirmed(reply):
        checks = json_reply(reply, list)
        if len(checks) != len(question["blanks"]):
            raise ValueError("詳解必須逐空核對")
        for i, check in enumerate(checks):
            if not isinstance(check, dict) or check.get("blank") != i + 1 or check.get("aligned") is not True:
                raise ValueError("詳解與已驗證答案不一致")
            quote = check.get("explanationQuote")
            if not isinstance(quote, str) or not quote.strip() or quote not in solution:
                raise ValueError("詳解核對必須逐字引用修訂後的解釋")
            proof(check, originals, images)
        return True

    await checkpoint(ctx, "fill-solution-review", FILL_SOLUTION_REVIEW + base + f"\n修訂詳解 JSON：{data(solution)}",
                     ANSWER_SYSTEM, confirmed, list(images.values()))
    return {**question, "solution": solution}
