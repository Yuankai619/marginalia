import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

// Use the existing compiler so these tests also run on Node versions without TS stripping.
const source = readFileSync(new URL("../src/lib/video.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
});
const { parseVideoLink, safeNoteUrl, videoSource } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

const validIds = [
  "os20260916", "video-b", "課堂一", "中文-錄影_１２３", "日本語", "한국어",
  "café", "Ελληνικά", "видео", "محاضرة١", "數字²Ⅳ", "𠮷𓀀", "_影片", "123",
];

test("accept backend Unicode word IDs, both literal and URL encoded", () => {
  for (const video of validIds) {
    for (const id of [video, encodeURIComponent(video)]) {
      const href = `video:${id}?t=12.5`;
      assert.deepEqual(parseVideoLink(href), { video, time: 12.5 }, href);
      assert.equal(safeNoteUrl(href), href);
    }
  }
});

test("reject IDs outside store.validate_id, including encoded path and scheme separators", () => {
  const invalidIds = [
    "", "-video", ".hidden", "video.v2", "../video", "a/b", "a\\b", "a b",
    "影片😀", "cafe\u0301", "a\n", "a\0", "video:other", "a?b", "a#b",
    "javascript:alert", "data:text", "%課堂", "%E8%AA", "%ZZ", "%252F",
  ];
  for (const id of invalidIds) {
    for (const value of [id, encodeURIComponent(id)]) {
      const href = `video:${value}?t=12`;
      assert.equal(parseVideoLink(href), null, href);
      assert.equal(safeNoteUrl(href), "", href);
    }
  }
});

test("accept finite nonnegative seconds and reject malformed timestamps", () => {
  assert.deepEqual(parseVideoLink("video:課堂一?t=0"), { video: "課堂一", time: 0 });
  for (const timestamp of ["", "-1", "NaN", "Infinity", "1e3", ".5", "1.", "1&x=2", "1#x", "1\n", "9".repeat(400)]) {
    assert.equal(parseVideoLink(`video:課堂一?t=${timestamp}`), null, timestamp);
  }
});

test("preserve only allowed schemes; decoding an ID cannot introduce a scheme", () => {
  for (const href of [
    "javascript:alert(1)", "data:text/html,test", "file:///tmp/video", "mailto:a@example.com",
    "//example.com/video", "/video", "https:video:課堂一?t=12", "video:javascript%3Aalert?t=12",
    "video%3A課堂一?t=12", "video:課堂一?t=12\njavascript:alert(1)",
  ]) {
    assert.equal(parseVideoLink(href), null, href);
    assert.equal(safeNoteUrl(href), "", href);
  }
  for (const href of ["https://example.com/video", "http://example.com/video"]) {
    assert.equal(parseVideoLink(href), null);
    assert.equal(safeNoteUrl(href), href);
  }
});

test("decoded Unicode IDs select the matching local or static video", () => {
  const course = {
    info: { videoUrls: { 課堂一: "https://example.com/chinese.mp4" } },
    videos: [{ id: "課堂一", source: "materials/課堂一.mp4" }],
  };
  const target = parseVideoLink("video:%E8%AA%B2%E5%A0%82%E4%B8%80?t=12");
  assert.equal(videoSource(course, "fixture", target.video, true), "/files/fixture/materials/%E8%AA%B2%E5%A0%82%E4%B8%80.mp4");
  assert.equal(videoSource(course, "fixture", target.video, false), "https://example.com/chinese.mp4");
  assert.equal(videoSource(course, "fixture", "不存在", true), null);
  assert.equal(videoSource(course, "fixture", "不存在", false), null);
});
