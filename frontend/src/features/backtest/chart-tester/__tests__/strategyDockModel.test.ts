import assert from "node:assert/strict";
import test from "node:test";
import { strategyDockHeight } from "../strategyDockModel.js";

test("normal dock leaves room for the chart even with a large saved height", () => {
  assert.equal(strategyDockHeight(900, 700), 460);
  assert.equal(strategyDockHeight(280, 700), 280);
  assert.equal(strategyDockHeight(900, 400), 180);
  assert.equal(strategyDockHeight(900, 300), 135);
});
test("only explicit maximize consumes the workspace; invalid saved sizes remain bounded", () => {
  assert.equal(strategyDockHeight(280, 700, true), 700);
  assert.equal(strategyDockHeight(NaN, 700), 280);
  assert.equal(strategyDockHeight(-100, 700), 260);
  assert.equal(strategyDockHeight(280, 0), 36);
});

test("expanded dock reserves useful report space when available but still protects a short chart", () => {
  assert.equal(strategyDockHeight(180, 700), 260);
  assert.equal(strategyDockHeight(180, 400), 180);
});
