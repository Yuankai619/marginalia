import assert from "node:assert/strict";
import test from "node:test";
import { load } from "./load-ts.mjs";

const { remarkAlerts, highlight } = await load("remark-notes");
const { reviewView, noteDigest } = await load("review");
const { sha256Hex } = await load("sha256");
const { assetUrl } = await load("assets");
const { timestampLabel, timestampLink, parseVideoLink } = await load("video");

const text = (value) => ({ type: "text", value });
const marks = (nodes) => nodes.map((n) => (n.type === "highlight" ? `<${n.children.map((c) => c.value ?? `[${c.type}]`).join("")}>` : (n.value ?? `[${n.type}]`))).join("");

test("==highlight== within and across inline nodes", () => {
  assert.equal(marks(highlight([text("a ==b== c")])), "a <b> c");
  assert.equal(marks(highlight([text("==x "), { type: "strong" }, text(" y== z")])), "<x [strong] y> z");
  assert.equal(marks(highlight([text("a == b")])), "a == b");
  assert.equal(marks(highlight([text("==a== ==b==")])), "<a> <b>");
  assert.equal(marks(highlight([text("x ==== y")])), "x ==== y");
  assert.equal(marks(highlight([text("若 pid == 0 是子行程，pid == -1 是錯誤")])), "若 pid == 0 是子行程，pid == -1 是錯誤");
  assert.equal(marks(highlight([text("a ==b == c== d")])), "a <b == c> d");
  assert.equal(marks(highlight([text("== 不算 ==")])), "== 不算 ==");
  assert.equal(marks(highlight([{ type: "strong" }, text("==x==")])), "[strong]<x>");
  assert.equal(marks(highlight([{ type: "inlineCode", value: "a==b==" }])), "a==b==");
});

test("GitHub alerts become labelled callouts", () => {
  const tree = {
    type: "root",
    children: [
      { type: "blockquote", children: [{ type: "paragraph", children: [text("[!IMPORTANT]\n結論")] }] },
      { type: "blockquote", children: [{ type: "paragraph", children: [text("[!caution]")] }, { type: "paragraph", children: [text("b")] }] },
      { type: "blockquote", children: [{ type: "paragraph", children: [text("[!OTHER] 一般引用")] }] },
    ],
  };
  remarkAlerts()(tree);
  const [important, caution, plain] = tree.children;
  assert.deepEqual(important.data.hProperties.className, ["alert", "alert-important"]);
  assert.equal(important.children[0].children[0].value, "重點");
  assert.equal(important.children[1].children[0].value, "結論");
  assert.equal(caution.children[0].children[0].value, "易混淆");
  assert.equal(caution.children.length, 2, "empty marker paragraph is dropped");
  assert.equal(plain.data, undefined);
});

const finding = (reviewer, severity, problem) => ({ reviewer, severity, quote: "q", problem, fix: "f" });

test("review: revised note, fixed vs still open", () => {
  const open = finding("rules", "high", "格式錯");
  const view = reviewView(
    { findings: [finding("correctness", "high", "錯"), finding("style", "low", "小"), open], unresolved: [open], revised: true, noteHash: "n", reviewedHash: "r" },
    "n",
  );
  assert.deepEqual(view.open.map((f) => f.problem), ["格式錯"]);
  assert.deepEqual(view.fixed.map((f) => f.problem), ["錯", "小"]);
  assert.equal(view.stale, false);
});

test("review: unrevised note keeps blocking findings open, low ones as suggestions", () => {
  const view = reviewView({ findings: [finding("style", "low", "小"), finding("coverage", "medium", "漏")], revised: false, noteHash: "n", reviewedHash: "n" }, "n");
  assert.deepEqual(view.open.map((f) => f.problem), ["漏"]);
  assert.deepEqual(view.suggestions.map((f) => f.problem), ["小"]);
  assert.equal(view.fixed.length, 0);
});

test("review: stale records are hidden, junk is tolerated", () => {
  assert.equal(reviewView({ findings: [finding("style", "high", "x")], noteHash: "n", reviewedHash: "r" }, "other").stale, true);
  assert.equal(reviewView({ findings: [finding("style", "high", "x")], noteHash: "n", reviewedHash: "r" }, "other").open.length, 0);
  const junk = reviewView({ findings: [null, 3, { problem: "" }, { problem: "p", severity: "weird" }], errors: { coverage: "timeout" } }, "d");
  assert.deepEqual(junk.open.map((f) => [f.problem, f.severity]), [["p", "medium"]]);
  assert.deepEqual(junk.failed, ["coverage"]);
  assert.equal(reviewView(null, "d"), null);
  assert.equal(reviewView("舊版文字", "d"), null);
  // Only the reviewed text's hash: current if it matches, stale otherwise.
  assert.equal(reviewView({ findings: [finding("style", "high", "x")], reviewedHash: "r" }, "r").open.length, 1);
  assert.equal(reviewView({ findings: [finding("style", "high", "x")], reviewedHash: "r" }, "other").stale, true);
});

test("asset URLs only resolve plain files under assets/", () => {
  assert.equal(assetUrl("os", "l1", "assets/cpu.svg"), "/files/os/notes/l1/assets/cpu.svg");
  assert.equal(assetUrl("os", "l1", "assets/架構圖-1a.png"), `/files/os/notes/l1/assets/${encodeURIComponent("架構圖-1a.png")}`);
  for (const bad of ["assets/../x.png", "assets/a/b.png", "../assets/x.png", "/etc/x.png", "https://x/y.png", "assets/x.html", "assets/.x.png", "assets/x.png?y", "assets/x.gif"])
    assert.equal(assetUrl("os", "l1", bad), null, bad);
});

test("timestamp links follow the note format", () => {
  assert.equal(timestampLabel(5), "00:05");
  assert.equal(timestampLabel(887.9), "14:47");
  assert.equal(timestampLabel(3725), "1:02:05");
  const link = timestampLink({ video: "課堂一", time: 61.4 });
  assert.equal(link, `[01:01](video:${encodeURIComponent("課堂一")}?t=61)`);
  assert.deepEqual(parseVideoLink(link.slice(link.indexOf("(") + 1, -1)), { video: "課堂一", time: 61 });
});

const { safeCss } = await load("safe-svg");

test("diagram CSS keeps in-document references only", () => {
  assert.equal(safeCss("marker-end:url(#arrow)"), "marker-end:url(#arrow)");
  assert.equal(safeCss("fill:url( 'https://evil.example/?d=x' )"), "fill:none");
  assert.equal(safeCss('background:url("//evil.example/a")'), "background:none");
  assert.equal(safeCss("@import url(https://evil.example/a.css); .a{fill:red}"), " .a{fill:red}");
  assert.equal(safeCss("fill:URL(data:image/png;base64,AA)"), "fill:none");
});


test("note digest matches the server (sha256 of the stripped body, 16 hex)", async () => {
  const bytes = (text) => new TextEncoder().encode(text);
  assert.equal(sha256Hex(bytes("")), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(sha256Hex(bytes("abc")), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  const long = "作業系統".repeat(500);
  const { createHash } = await import("node:crypto");
  assert.equal(sha256Hex(bytes(long)), createHash("sha256").update(long).digest("hex"));
  assert.equal(noteDigest(`\n ${long} \n`), createHash("sha256").update(long).digest("hex").slice(0, 16));
});
