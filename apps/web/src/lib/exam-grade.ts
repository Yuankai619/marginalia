// Objective grading for the static reader; the same rules as server/marginalia/exam/grade.py
// (docs/architecture.md, Exam prep), tested against server/tests/exam/grade_cases.json.
import type { Answer, Question, QuestionResult } from "./exam-types";

export const SUBJECTIVE = new Set(["short", "essay", "calc"]);

// Upper then lower, as grade.normalize does: folds ß to ss like Python's casefold() would.
const normalize = (text: string) =>
  text
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase()
    .toLowerCase();

// Nearest 0.5, halves up (Python uses floor(x * 2 + 0.5) / 2 for the same result).
const half = (value: number) => Math.floor(value * 2 + 0.5) / 2;

export function gradeObjective(
  question: Question,
  answer: Answer | undefined | null,
): QuestionResult {
  const points = question.points;
  if (question.type === "choice") {
    const picked = new Set(
      Array.isArray(answer)
        ? answer.filter((a): a is string => typeof a === "string")
        : [],
    );
    if (!picked.size) return { status: "blank", score: 0, maxScore: points };
    const right = new Set(question.answer ?? []);
    const ok =
      picked.size === right.size && [...picked].every((a) => right.has(a));
    return {
      status: ok ? "correct" : "incorrect",
      score: ok ? points : 0,
      maxScore: points,
    };
  }
  if (question.type === "fill") {
    const blanks = question.blanks ?? [];
    const values = Array.isArray(answer) ? answer : [];
    const given = blanks.map((_, i) =>
      typeof values[i] === "string" ? normalize(values[i]) : "",
    );
    if (!given.some(Boolean))
      return { status: "blank", score: 0, maxScore: points };
    const right = blanks.filter((accepted, i) =>
      accepted.map(normalize).includes(given[i]),
    ).length;
    return {
      status:
        right === blanks.length ? "correct" : right ? "partial" : "incorrect",
      score: half((points * right) / blanks.length),
      maxScore: points,
    };
  }
  if (typeof answer !== "string" || !answer.trim())
    return { status: "blank", score: 0, maxScore: points };
  return { status: "pending", score: null, maxScore: points };
}

export function totals(results: Record<string, QuestionResult>) {
  const values = Object.values(results);
  return {
    score: values.reduce((sum, r) => sum + (r.score ?? 0), 0),
    maxScore: values.reduce((sum, r) => sum + r.maxScore, 0),
  };
}
