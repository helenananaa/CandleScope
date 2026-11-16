import assert from "node:assert/strict";
import test from "node:test";
import { HEADER_COMPACT_BEFORE_ACTIONS, HEADER_COMPACT_LEVELS, chooseHeaderCompaction, fitHeaderActions } from "../headerActionsModel.js";

test("header actions stay inline while they all fit", () => {
  assert.equal(fitHeaderActions([80, 90], 178, 8, 32), 2);
  assert.equal(fitHeaderActions([], 0, 8, 32), 0);
});

test("when they do not fit, later actions move into the menu and room is kept for its button", () => {
  // 80 + 8 + 90 = 178 > 170: keep the 32px menu button, then fit in order.
  assert.equal(fitHeaderActions([80, 90], 170, 8, 32), 1);
  assert.equal(fitHeaderActions([80, 90, 60], 200, 8, 32), 1);
  assert.equal(fitHeaderActions([80, 90, 60], 220, 8, 32), 2);
  // Too narrow for any action beside the menu button.
  assert.equal(fitHeaderActions([80, 90], 100, 8, 32), 0);
});

test("the header compacts details before page actions, and badges and labels only after them", () => {
  // A header whose left side fits from level `mainFitsAt` and whose actions fit from `actionsFitAt`.
  const run = (mainFitsAt: number, actionsFitAt: number, start = 0) => {
    let level = 0;
    const applied: number[] = [];
    const chosen = chooseHeaderCompaction((next) => { level = next; applied.push(next); }, {
      mainOverflows: () => level < mainFitsAt,
      actionsFit: () => level >= actionsFitAt,
    }, start);
    return { chosen, applied };
  };
  assert.equal(run(0, 0).chosen, 0);
  // Actions that do not fit take the early steps, but never the later ones: they go to 更多 instead.
  assert.equal(run(0, 1).chosen, 1);
  assert.equal(run(0, 9).chosen, HEADER_COMPACT_BEFORE_ACTIONS);
  // A left side that still overflows takes every step.
  assert.equal(run(3, 0).chosen, 3);
  assert.equal(run(9, 0).chosen, HEADER_COMPACT_LEVELS);
  // A content change starts from the current level, so the header never relaxes without a resize.
  assert.deepEqual(run(0, 0, 3), { chosen: 3, applied: [3] });
});
