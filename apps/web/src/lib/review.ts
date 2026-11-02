// Turns a review record (`generated/reviews/<deck>/NNN.json`, written by the notes reviewers) into what the
// 筆記檢查 tab shows. Records are produced by an LLM pipeline, so every field is treated as optional.

import { sha256Hex } from "./sha256";

export type Severity = "high" | "medium" | "low";
export type Finding = {
  reviewer: string;
  severity: Severity;
  quote: string;
  problem: string;
  fix: string;
};
type ReviewRecord = {
  findings?: unknown;
  unresolved?: unknown;
  revised?: unknown;
  reviewedAt?: unknown;
  noteHash?: unknown;
  reviewedHash?: unknown;
  errors?: unknown;
};
export type ReviewView = {
  open: Finding[];
  fixed: Finding[];
  suggestions: Finding[];
  reviewedAt: string | null;
  revised: boolean;
  /** Reviewers that failed this run (their findings are missing). */
  failed: string[];
  /** The note changed after the review; the record no longer describes it and is not shown. */
  stale: boolean;
};

export const REVIEWERS: Record<string, { name: string; role: string }> = {
  correctness: {
    name: "內容正確性",
    role: "對照投影片與逐字稿，找錯誤與錯的時間點",
  },
  "codex-correctness": {
    name: "內容正確性（第二意見）",
    role: "另一個模型再核對一次事實",
  },
  style: { name: "好不好讀", role: "沒有基礎的人能不能看懂、條理清不清楚" },
  coverage: { name: "重點有沒有漏", role: "老師講到但筆記沒寫的重點" },
  rules: { name: "格式規範", role: "自動檢查格式：提示框、螢光筆、圖表語法" },
};

export const SEVERITY: Record<
  Severity,
  { label: string; tone: "danger" | "warning" | "neutral" }
> = {
  high: { label: "需要修正", tone: "danger" },
  medium: { label: "建議修改", tone: "warning" },
  low: { label: "小細節", tone: "neutral" },
};

const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };

const text = (value: unknown) => (typeof value === "string" ? value : "");

function finding(value: unknown): Finding | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const problem = text(raw.problem).trim();
  if (!problem) return null;
  const severity = (["high", "medium", "low"] as const).includes(
    raw.severity as Severity,
  )
    ? (raw.severity as Severity)
    : "medium";
  return {
    reviewer: text(raw.reviewer) || "rules",
    severity,
    quote: text(raw.quote).trim(),
    problem,
    fix: text(raw.fix).trim(),
  };
}

const findings = (value: unknown): Finding[] =>
  (Array.isArray(value) ? value : [])
    .map(finding)
    .filter((item): item is Finding => item !== null);

const key = (f: Finding) => `${f.reviewer}\u0000${f.quote}\u0000${f.problem}`;
const bySeverity = (a: Finding, b: Finding) =>
  SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];

/**
 * `findings` describe the text the reviewers read (`reviewedHash`), `unresolved` the text the review left on disk
 * (`noteHash`). With the current note's `digest`:
 * - it is `noteHash`: `unresolved` are open; when the note was revised every other finding counts as fixed,
 *   otherwise high/medium findings are open and low ones are suggestions.
 * - it is only `reviewedHash` (the revision was undone): findings apply as written, nothing counts as fixed.
 * - it matches neither: the record is stale and its findings are not shown.
 * A record with neither hash predates them and is taken as it is.
 */
export function reviewView(record: unknown, digest: string): ReviewView | null {
  if (!record || typeof record !== "object") return null;
  const raw = record as ReviewRecord;
  const noteHash = text(raw.noteHash);
  const reviewedHash = text(raw.reviewedHash);
  const legacy = !noteHash && !reviewedHash;
  const onDisk = legacy || digest === noteHash;
  const stale = !onDisk && digest !== reviewedHash;
  const revised = raw.revised === true && onDisk;
  const errors =
    raw.errors && typeof raw.errors === "object" ? Object.keys(raw.errors) : [];
  const base = {
    reviewedAt: text(raw.reviewedAt) || null,
    revised,
    failed: errors,
    stale,
  };
  if (stale) return { ...base, open: [], fixed: [], suggestions: [] };
  const all = findings(raw.findings);
  const unresolved = onDisk ? findings(raw.unresolved) : [];
  const pending = new Set(unresolved.map(key));
  const open = [...unresolved];
  const fixed: Finding[] = [];
  const suggestions: Finding[] = [];
  for (const item of all) {
    if (pending.has(key(item))) continue;
    if (revised) fixed.push(item);
    else if (item.severity === "low") suggestions.push(item);
    else open.push(item);
  }
  return {
    ...base,
    open: open.sort(bySeverity),
    fixed: fixed.sort(bySeverity),
    suggestions,
  };
}

/** Same digest as notefile.digest on the server: sha256 of the stripped body, first 16 hex chars. */
export const noteDigest = (body: string) =>
  sha256Hex(new TextEncoder().encode(body.trim())).slice(0, 16);

/** One line for the note banner, the tab badge and the checks tab, so they never disagree. */
export function checkSummary(view: ReviewView): {
  tone: "warning" | "success";
  title: string;
  count: number;
} {
  if (view.failed.length)
    return {
      tone: "warning",
      title: `筆記檢查沒有做完：${view.failed.map((id) => REVIEWERS[id]?.name ?? id).join("、")}這次沒有跑完`,
      count: view.open.length || view.failed.length,
    };
  if (view.open.length)
    return {
      tone: "warning",
      title: `還有 ${view.open.length} 項需要你看一下`,
      count: view.open.length,
    };
  const total = view.fixed.length + view.suggestions.length;
  return {
    tone: "success",
    title: !total
      ? "檢查通過，沒有發現問題"
      : view.fixed.length
        ? `檢查通過，已自動修正 ${view.fixed.length} 項`
        : "檢查通過，只有幾項小建議",
    count: 0,
  };
}
