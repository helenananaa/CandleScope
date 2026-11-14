import assert from "node:assert/strict";
import test from "node:test";

import { compareHtml, labelPrefix, mergeManifest, parseArgs, snapshotFileName, STATES } from "./design-snapshots.mjs";

test("defaults capture every state in both themes at 1440x900", () => {
  const args = parseArgs(["--label", "baseline"]);
  assert.deepEqual(args.themes, ["dark", "light"]);
  assert.deepEqual(args.viewports, [{ width: 1440, height: 900 }]);
  assert.deepEqual(args.states, []);
  assert.match(args.out.split("\\").join("/"), /output\/design-snapshots\/baseline$/);
});

test("options narrow states, themes and viewports and reject unknown values", () => {
  const args = parseArgs(["--states", "market,alerts", "--themes", "light", "--viewports", "1024x768,1366x768"]);
  assert.deepEqual(args.states, ["market", "alerts"]);
  assert.deepEqual(args.themes, ["light"]);
  assert.deepEqual(args.viewports, [{ width: 1024, height: 768 }, { width: 1366, height: 768 }]);
  assert.throws(() => parseArgs(["--states", "nope"]), /Unknown state/);
  assert.throws(() => parseArgs(["--themes", "sepia"]), /Unknown theme/);
  assert.throws(() => parseArgs(["--viewports", "wide"]), /Viewport/);
  assert.throws(() => parseArgs(["--bogus"]), /Unknown option/);
});

test("state names are unique and file names encode state, theme and viewport", () => {
  const names = STATES.map((state) => state.name);
  assert.equal(new Set(names).size, names.length);
  assert.equal(snapshotFileName("alerts", "light", { width: 1024, height: 768 }), "alerts--light--1024x768.png");
});

test("label prefixes drop counts and shortcut hints", () => {
  assert.equal(labelPrefix("指标 3"), "指标 3");
  assert.equal(labelPrefix("搜索交易对 (⌘+K)"), "搜索交易对");
  assert.equal(labelPrefix("当前窗口布局: {name}"), "当前窗口布局:");
});

test("the comparison page pairs the same file from both runs", () => {
  const html = compareHtml("/tmp/snaps/baseline", "/tmp/snaps/after", ["market--dark--1440x900.png"]);
  assert.match(html, /src="\.\.\/baseline\/market--dark--1440x900\.png"/);
  assert.match(html, /src="market--dark--1440x900\.png"/);
});

test("later runs into the same label merge into the manifest", () => {
  const previous = { label: "baseline", shots: [{ file: "a--dark--1440x900.png" }, { file: "b--dark--1440x900.png", problems: ["x"] }] };
  const next = { label: "baseline", shots: [{ file: "b--dark--1440x900.png", problems: [] }, { file: "c--dark--1024x768.png" }] };
  assert.deepEqual(mergeManifest(previous, next).shots.map((shot) => shot.file),
    ["a--dark--1440x900.png", "b--dark--1440x900.png", "c--dark--1024x768.png"]);
  assert.deepEqual(mergeManifest(previous, next).shots[1].problems, []);
  assert.equal(mergeManifest(null, next), next);
});
