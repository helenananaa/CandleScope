import assert from "node:assert/strict";
import test from "node:test";
import { constrainReadablePaneHeights, readablePaneMinimums } from "../paneReadableHeight.js";

test("minimums follow identities through reorder and intentional collapse", () => {
  assert.deepEqual(readablePaneMinimums(["rsi", "main", "macd"], [], null), [80, 180, 80]);
  assert.deepEqual(readablePaneMinimums(["main", "rsi"], ["rsi"], null), [180, 36]);
  assert.deepEqual(readablePaneMinimums(["main", "rsi"], [], "rsi"), [36, 80]);
});

test("small saved ratios are repaired within the real available budget", () => {
  const fixed = constrainReadablePaneHeights([420, 30, 30, 30, 30], [180, 80, 80, 80, 80]);
  assert.deepEqual(fixed, [220, 80, 80, 80, 80]);
  assert.equal(fixed?.reduce((sum, height) => sum + height, 0), 540);
  assert.equal(constrainReadablePaneHeights(fixed!, [180, 80, 80, 80, 80]), null);
});

test("valid user proportions and unsettled insufficient budgets are untouched", () => {
  assert.equal(constrainReadablePaneHeights([300, 100], [180, 80]), null);
  assert.equal(constrainReadablePaneHeights([180, 30], [180, 80]), null);
  assert.equal(constrainReadablePaneHeights([NaN], [80]), null);
  assert.equal(constrainReadablePaneHeights([80], [80, 80]), null);
});
