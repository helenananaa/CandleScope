import assert from "node:assert/strict";
import test from "node:test";
import { AUDIT, composite, contrastRatio, groupFailures, parseColor, requiredRatio } from "./design-contrast.mjs";

test("colours parse as the browser reports them and composite over their background", () => {
  assert.deepEqual(parseColor("rgb(23, 24, 27)"), [23, 24, 27, 1]);
  assert.deepEqual(parseColor("rgba(0, 0, 0, 0.5)"), [0, 0, 0, 0.5]);
  assert.equal(parseColor("transparent"), null);
  assert.deepEqual(composite([0, 0, 0, 0.5], [255, 255, 255, 1]), [127.5, 127.5, 127.5, 1]);
});

test("contrast follows WCAG: 21:1 at most, 4.5:1 for body text and 3:1 for large text", () => {
  assert.equal(Math.round(contrastRatio([0, 0, 0], [255, 255, 255])), 21);
  assert.equal(requiredRatio(14, 400), 4.5);
  assert.equal(requiredRatio(24, 400), 3);
  assert.equal(requiredRatio(19, 700), 3);
  assert.equal(requiredRatio(19, 400), 4.5);
});

test("failures that share colours and component are grouped, worst first", () => {
  const groups = groupFailures([
    { state: "market", theme: "light", fg: "a", bg: "b", where: "span.x", text: "1", ratio: 3.7 },
    { state: "market", theme: "light", fg: "a", bg: "b", where: "span.x", text: "2", ratio: 3.7 },
    { state: "market", theme: "light", fg: "c", bg: "b", where: "span.y", text: "3", ratio: 2.1 },
  ]);
  assert.deepEqual(groups.map((group) => [group.where, group.count]), [["span.y", 1], ["span.x", 2]]);
});

test("the in-page audit skips disabled controls, canvases and SVG", () => {
  assert.match(AUDIT, /:disabled, \[aria-disabled=true\], \[inert\], svg, canvas/);
});
