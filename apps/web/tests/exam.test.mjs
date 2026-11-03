import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { load } from "./load-ts.mjs";

const { gradeObjective } = await load("exam-grade");
const { imageUrl } = await load("assets");
const cases = JSON.parse(readFileSync(new URL("../../../server/tests/exam/grade_cases.json", import.meta.url), "utf8"));

test("objective grading matches the server's cases", () => {
  for (const c of cases.cases) {
    const question = cases.questions.find((q) => q.id === c.question);
    const result = gradeObjective(question, c.answer);
    assert.deepEqual([result.status, result.score], [c.status, c.score], `${c.question} ${JSON.stringify(c.answer)}`);
  }
});

test("handout images resolve slides and exam assets only", () => {
  const exam = { courseId: "os", examId: "midterm" };
  assert.equal(imageUrl(exam, "slide:l2-processes/7"), "/files/os/generated/decks/l2-processes/slides/007.webp");
  assert.equal(imageUrl(exam, "assets/圖.png"), "/files/os/exams/midterm/handout/assets/%E5%9C%96.png");
  assert.equal(imageUrl({ ...exam, decks: ["l1"] }, "slide:l2-processes/7"), null);
  for (const bad of ["slide:../x/1", "slide:l2/0", "slide:l2/x", "assets/../exam.json", "https://x.example/a.png", "uploads/a.png"])
    assert.equal(imageUrl(exam, bad), null, bad);
  assert.equal(imageUrl({ courseId: "os", deckId: "l1" }, "slide:l1/1"), null);
});
