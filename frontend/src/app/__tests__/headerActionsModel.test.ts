import assert from "node:assert/strict";
import test from "node:test";
import { fitHeaderActions } from "../headerActionsModel.js";

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
