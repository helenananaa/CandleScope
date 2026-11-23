import assert from "node:assert/strict";
import test from "node:test";
import { AUDIT, DEFAULT_LOCALES, DEFAULT_VIEWPORTS, boxesOverlap, groupFindings, hasFullText, overflows, parseArgs } from "./design-layout.mjs";

test("text is cut when its box is wider than its room by more than a pixel", () => {
  assert.equal(overflows(101, 100), false, "rounding");
  assert.equal(overflows(102.5, 100), true);
});

test("controls overlap when they share more than two pixels on both axes", () => {
  const a = { left: 0, right: 50, top: 0, bottom: 20 };
  assert.equal(boxesOverlap(a, { left: 49, right: 90, top: 0, bottom: 20 }), false, "touching edges");
  assert.equal(boxesOverlap(a, { left: 40, right: 90, top: 0, bottom: 20 }), true);
  assert.equal(boxesOverlap(a, { left: 40, right: 90, top: 30, bottom: 50 }), false, "different rows");
});

test("findings group by kind, component and text across visits, most frequent first", () => {
  const groups = groupFindings([
    { kind: "cut", where: "span.a", text: "Watchlist", state: "market", locale: "en", viewport: "1024x768" },
    { kind: "cut", where: "span.a", text: "Watchlist", state: "market", locale: "en", viewport: "1366x768" },
    { kind: "select", where: "select", text: "Controller group", state: "market", locale: "de", viewport: "1024x768" },
  ]);
  assert.deepEqual(groups.map((group) => [group.text, group.visits.length]), [["Watchlist", 2], ["Controller group", 1]]);
});

test("a shortened text counts as on hover only when its title or name holds all of it", () => {
  assert.equal(hasFullText({ kind: "cut", text: "bt_0967…", full: "bt_09670ba912054af2b97b352235104431" }), true);
  assert.equal(hasFullText({ kind: "select", text: "Controller group", full: "Controller group" }), true);
  assert.equal(hasFullText({ kind: "cut", text: "Positions, journal and review", full: "" }), false);
  assert.equal(hasFullText({ kind: "cut", text: "Strikt", full: "Aggregierte Trade-IDs sind kontinuierlich" }), false, "a title that explains is not the text");
  assert.equal(hasFullText({ kind: "overlap", text: "4H ↔ 1D", full: "4H ↔ 1D" }), false);
  assert.equal(hasFullText({ kind: "spill", text: "Последняя", full: "Последняя · Сортировать" }), false, "spilt text runs over its neighbour");
});

test("the audit covers four widths and the longest languages, dark theme unless asked", () => {
  assert.deepEqual(DEFAULT_VIEWPORTS.map((v) => v.width), [1024, 1366, 1440, 1920]);
  assert.deepEqual(DEFAULT_LOCALES, ["zh-CN", "en", "de", "ru"]);
  const args = parseArgs(["--locales", "en,ru", "--viewports", "1024x768"]);
  assert.deepEqual(args.locales, ["en", "ru"]);
  assert.deepEqual(args.themes, ["dark"]);
  assert.match(args.out, /output\/design-layout\//);
  // Scroll containers do not cut text; a chevron drawn over a select takes its room; overlaps are
  // measured on what is shown, and a button a field keeps room for is not on top of it.
  assert.match(AUDIT, /scrolls\(ns\)\) break/);
  assert.match(AUDIT, /room -= covered/);
  assert.match(AUDIT, /insideField\(a, b\)/);
  assert.match(AUDIT, /add\("spill"/);
});
