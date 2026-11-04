"""Compare final mechanisms/formulas with complete sources, including corrections."""

from __future__ import annotations

from .. import config
from .context import ExamContext
from .evidence import full_material, images_for, proof, source_batches
from .generation import GenerationError, batches, checkpoint, data, parallel
from .prompts import (
    CLAIM_INVENTORY,
    CLAIM_RECONCILE,
    CLAIM_REPAIR,
    CLAIM_SYSTEM,
    CLAIM_TASK,
)
from .schema import json_reply


async def verify_claims(ctx: ExamContext, body: str, refs: list[str], parse_body) -> str:
    for attempt in range(3):
        def inventory(reply, body=body):
            raw = json_reply(reply, list)
            if not raw or len(raw) > 60:
                raise ValueError("每節最多列 60 個可核對的 claim")
            if any(not isinstance(q, str) or not q.strip() or q not in body for q in raw) or len(raw) != len(set(raw)):
                raise ValueError("claim 必須逐字摘自正文且不可重複")
            return raw

        claims = await checkpoint(ctx, "claim-inventory", f"{CLAIM_INVENTORY}\n正文 JSON：{data(body)}", CLAIM_SYSTEM, inventory)
        async def check(job, body=body):
            originals, group = job
            selected_claims = [text for _, text in group]
            images = images_for(ctx, originals)
            def parse(reply):
                raw = json_reply(reply, list)
                if len(raw) != len(selected_claims):
                    raise ValueError("必須逐項核對全部 claim")
                if any(not isinstance(c, dict) for c in raw):
                    raise TypeError("claim 核對必須是 JSON 物件")
                for i, item in enumerate(raw):
                    if item.get("claim") != i + 1 or item.get("status") not in ("supported", "conflict", "unknown"):
                        raise ValueError("claim 核對的編號與狀態不符")
                    if item["status"] != "unknown":
                        proof(item, originals, images)
                    if item["status"] == "conflict" and (not item.get("correction") or not item.get("counterexample")):
                        raise ValueError("分歧必須附修正與條件／數值反例")
                return raw

            result = await checkpoint(ctx, "claim-evidence", f"{CLAIM_TASK}\n完整正文 JSON：{data(body)}\nclaim JSON：{data(selected_claims)}\n完整來源 JSON：{data(originals)}\n附圖順序 JSON：{data(list(images))}",
                                      CLAIM_SYSTEM, parse, list(images.values()), attempts=3)
            return {index: verdict for (index, _), verdict in zip(group, result, strict=True)}

        groups = batches(list(enumerate(claims)), maximum=8)
        jobs = [(originals, group) for originals in source_batches(ctx, refs) for group in groups]
        checked = await parallel(jobs, check, config.GEN_CONCURRENCY)
        issues = []
        for i, claim in enumerate(claims):
            verdicts = [batch[i] for batch in checked if i in batch]
            conflicts = [v for v in verdicts if v["status"] == "conflict"]
            if conflicts:
                nonempty = [v for v in verdicts if v["status"] != "unknown"]
                refs_to_check = list(dict.fromkeys(v["source"] for v in nonempty))
                if len(refs_to_check) > 1:
                    decision = await reconcile(ctx, claim, nonempty, refs_to_check, body)
                    conflicts = [decision] if decision["status"] == "conflict" else []
                for conflict in conflicts:
                    issues.append({**conflict, "claim": claim, "contextRefs": refs_to_check})
            elif not any(v["status"] == "supported" for v in verdicts):
                issues.append({"claim": claim, "status": "unknown", "correction": "刪除無來源支持的論述，或明確標示無法確認"})
        if not issues:
            return body
        if attempt == 2:
            raise GenerationError("機制或公式與完整來源仍有分歧，未寫入講義")
        grouped = {}
        for issue in issues:
            grouped.setdefault(tuple(issue.get("contextRefs") or ([issue["source"]] if issue.get("source") else [])), []).append(issue)
        for source_refs, findings in grouped.items():
            originals = full_material(ctx, list(source_refs))
            images = images_for(ctx, originals)
            prompt = (f"{CLAIM_REPAIR}\n正文 JSON：{data(body)}\n核對分歧 JSON：{data(findings)}"
                      f"\n回查完整來源 JSON：{data(originals)}\n附圖順序 JSON：{data(list(images))}")
            body = await checkpoint(ctx, "claim-repair", prompt, CLAIM_SYSTEM, parse_body,
                                    list(images.values()), attempts=4)

    raise GenerationError("機制或公式與完整來源仍有分歧，未寫入講義")


async def reconcile(ctx: ExamContext, claim: str, verdicts: list[dict], refs: list[str], body: str) -> dict:
    originals = full_material(ctx, refs)
    images = images_for(ctx, originals)

    def parse(reply):
        decision = json_reply(reply, dict)
        if decision.get("status") not in ("supported", "conflict", "unknown") or not decision.get("reason"):
            raise ValueError("跨來源裁決須有狀態與適用條件理由")
        if decision["status"] != "unknown":
            proof(decision, originals, images)
        if decision["status"] == "conflict" and (not decision.get("correction") or not decision.get("counterexample")):
            raise ValueError("跨來源分歧須有修正及反例")
        return decision

    prompt = (f"{CLAIM_RECONCILE}\n完整正文 JSON：{data(body)}\nclaim JSON：{data(claim)}\n原核對分歧 JSON：{data(verdicts)}"
              f"\n回查完整來源 JSON：{data(originals)}\n附圖順序 JSON：{data(list(images))}")
    decision = await checkpoint(ctx, "claim-reconcile", prompt, CLAIM_SYSTEM, parse, list(images.values()))
    if decision["status"] == "unknown":
        raise GenerationError("來源間存在無法裁決的機制／公式分歧，未寫入講義")
    return decision
