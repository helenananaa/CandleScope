import assert from "node:assert/strict";
import test from "node:test";
import {
  defaultForwardLeverage, forwardAccountLeverage, forwardExecutionModel, forwardModelExecution, validForwardLeverage,
} from "./continuousAccountRules.js";

const initialization = { runId: "bt_research", versionHash: `sha256:${"1".repeat(64)}`, outputMode: "SIGNAL" as const, warmupBars: 0 };
const settings = { from: "2026-11-01T00:00", balance: "1000", percent: "10", fee: "4", slippage: "1", output: "SIGNAL" as const };

test("new forward runs trade on the practice account model; continued and saved runs keep theirs (ADR-BACKTEST-015 P6e)", () => {
  assert.equal(forwardExecutionModel(undefined, null), "PRACTICE");
  assert.equal(forwardExecutionModel(undefined, { settings: { ...settings, leverage: "10" } }), "PRACTICE");
  assert.equal(forwardExecutionModel(undefined, { settings }), "LEGACY", "a reference from before carries no leverage");
  assert.equal(forwardExecutionModel(initialization, null), "V2");
  assert.equal(forwardExecutionModel({ ...initialization, executionModel: "LEGACY" }, null), "LEGACY");
  assert.equal(forwardExecutionModel({ ...initialization, executionModel: "PRACTICE" }, { settings }), "PRACTICE");
});

test("leverage is a practice account's on futures and 1 elsewhere", () => {
  assert.equal(defaultForwardLeverage("futures"), "10");
  assert.equal(defaultForwardLeverage("spot"), "1");
  assert.equal(defaultForwardLeverage("futures", { initialBalance: "1", equityPercent: "1", leverage: "5", feeBps: "0", slippageBps: "0" }), "5");
  assert.equal(forwardAccountLeverage("PRACTICE", "futures", "5"), "5");
  assert.equal(forwardAccountLeverage("PRACTICE", "spot", "5"), "1");
  assert.equal(forwardAccountLeverage("LEGACY", "futures", "5"), "1");
  assert.deepEqual(["1", "125", "2.5"].map(validForwardLeverage), [true, true, true]);
  assert.deepEqual(["0", "126", "", "1e2", "-1"].map(validForwardLeverage), [false, false, false, false, false]);
});

test("each model adds its own execution fields", () => {
  assert.deepEqual(forwardModelExecution("PRACTICE", "10"), { account_rules: "PRACTICE_V1", leverage: "10" });
  assert.deepEqual(forwardModelExecution("LEGACY", "1"), {});
  assert.equal(forwardModelExecution("V2", "1").execution_model_revision, "EXECUTION_REALISM_V2");
});
