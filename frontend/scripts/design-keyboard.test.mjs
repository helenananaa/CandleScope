import assert from "node:assert/strict";
import test from "node:test";
import { ALLOWED_REDUCED_MOTION, PAGE, focusIndicator, parseArgs, popupProblems, walkEnd } from "./design-keyboard.mjs";

test("a focus indicator needs a visible change with 3:1 against what is around it", () => {
  assert.deepEqual(focusIndicator([], () => 0), { verdict: "none", ratio: 0, by: "" });
  const ring = [{ target: "self", prop: "outlineColor", ratio: 5.5 }];
  assert.equal(focusIndicator(ring, (change) => change.ratio).verdict, "ok");
  const halo = [{ target: "self", prop: "outlineColor", ratio: 1.7 }, { target: "self", prop: "backgroundColor", ratio: 1.2 }];
  const weak = focusIndicator(halo, (change) => change.ratio);
  assert.equal(weak.verdict, "weak");
  assert.equal(weak.ratio, 1.7);
});

test("a Tab walk ends back at the start, out of the page, stuck on one element, or at the limit", () => {
  assert.equal(walkEnd([{ index: 0 }, { index: 1 }, { index: 0 }], 100), "cycled");
  assert.equal(walkEnd([{ index: 0 }, { body: true }], 100), "left the page");
  assert.equal(walkEnd([{ index: 0 }, { index: 1 }, { index: 1 }, { index: 1 }], 100), "stuck");
  assert.equal(walkEnd([{ index: 0 }, { index: 1 }], 2), "limit");
  assert.equal(walkEnd([{ index: 0 }, { index: 1 }], 100), "");
});

test("a popup opens on Enter, takes focus, moves with arrows, closes on Escape and gives focus back", () => {
  const good = { opened: true, focusInside: true, moves: true, closed: true, returned: true };
  assert.deepEqual(popupProblems(good), []);
  assert.deepEqual(popupProblems({ opened: false }), ["does not open on Enter"]);
  assert.deepEqual(popupProblems({ ...good, focusInside: false, pointsInside: true }), [], "a combobox points into its list");
  assert.deepEqual(popupProblems({ ...good, focusInside: false }), ["focus stays outside the popup"]);
  assert.deepEqual(popupProblems({ ...good, moves: false }), ["arrow keys do not move"]);
  assert.deepEqual(popupProblems({ ...good, closed: false, closedOnSecondEscape: true }), ["Escape closes only on the second press"]);
  assert.deepEqual(popupProblems({ ...good, returned: false }), ["focus does not return to the trigger"]);
  assert.deepEqual(popupProblems({ skipped: "could not focus" }), []);
});

test("the audit runs the dark theme unless asked, and only spinners may keep moving", () => {
  const args = parseArgs(["--states", "market", "--max-stops", "40"]);
  assert.deepEqual(args.themes, ["dark"]);
  assert.equal(args.maxStops, 40);
  assert.match(args.out, /output\/design-keyboard\//);
  assert.ok(ALLOWED_REDUCED_MOTION.test("sym-spin"));
  assert.ok(!ALLOWED_REDUCED_MOTION.test("ui-fade-in"));
  // Focus styles that fade in are read once their transition has finished.
  assert.match(PAGE, /CSSTransition/);
});
