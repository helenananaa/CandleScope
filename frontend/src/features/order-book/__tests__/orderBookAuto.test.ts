import assert from "node:assert/strict";
import test from "node:test";
import { AutoGroupingState } from "../orderBookAuto.js";

test("auto requires sustained improvement and cooldown, and cancels pending changes when frozen", () => {
  const state = new AutoGroupingState();
  const fine = new Map([[1, 0], [2, 1]]);
  const coarse = new Map([[1, 1], [2, 0]]);
  assert.equal(state.choose(fine, 0), 1);
  assert.equal(state.choose(coarse, 1000), 1);
  assert.equal(state.choose(coarse, 3000), 1);
  assert.equal(state.choose(fine, 4000), 1);
  assert.equal(state.choose(coarse, 5000), 1);
  assert.equal(state.choose(coarse, 7000), 2);
  assert.equal(state.choose(fine, 20000, true), 2);
  assert.equal(state.choose(fine, 30000), 2);
  assert.equal(state.choose(fine, 32000), 1);
  assert.equal(state.choose(new Map([[1, 0.2], [2, 0]]), 50000), 1);
  state.reset();
  assert.equal(state.choose(coarse, 51000), 2);
});
