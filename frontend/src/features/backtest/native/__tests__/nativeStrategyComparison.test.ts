import assert from "node:assert/strict";
import test from "node:test";
import { comparisonMetrics, conditionStatus, comparisonConditions } from "../nativeStrategyComparisonModel.js";
import type { NativeRun } from "../nativeBacktestApi.js";

const run = (values: number[], mode: "NATIVE" | "CANDLESCOPE" = "NATIVE"): NativeRun => ({
  run_id: "test", state: "COMPLETED", created_at_ms: 0, execution_mode: mode,
  runtime_identity: { engine: { package: "engine", version: "1", code_sha256: "hash" } },
  result: { account_authority: "engine", fill_model: "bar", report_hash: "result", equity: values.map((value, time) => ({ time, value })),
    trades: [{ profit: 3 }, { profit: -1 }], orders: [], bars: [], graphics: [], raw_output: {}, diagnostics: [] },
});
test("comparison uses first sample return and running-peak drawdown", () => {
  const value = comparisonMetrics(run([100, 200, 150, 180]));
  assert.equal(value.returns, 80);
  assert.equal(value.maxDrawdown, 25);
  assert.equal(value.winRate, 50);
  assert.equal(value.points[2]?.drawdownPct, -25);
});
test("missing samples and zero baselines do not become fabricated returns", () => {
  assert.equal(comparisonMetrics(run([])).returns, null);
  assert.equal(comparisonMetrics(run([100])).maxDrawdown, null);
  assert.equal(comparisonMetrics(run([0, 100])).returns, null);
});
test("external fills are not treated as closed trade win rates", () => {
  assert.equal(comparisonMetrics(run([100, 110], "CANDLESCOPE")).winRate, null);
  const incomplete = run([100, 110]);
  incomplete.result!.trades.push({});
  assert.equal(comparisonMetrics(incomplete).winRate, null);
});
test("unknown conditions are not equality and known differences remain visible", () => {
  assert.equal(conditionStatus([null, null]), "unknown");
  assert.equal(conditionStatus(["10", null]), "unknown");
  assert.equal(conditionStatus(["10", "20", null]), "different");
  assert.equal(conditionStatus(["10", "10"]), "same");
  assert.equal(comparisonConditions(run([100, 110])).fees, null);
});
test("long histories avoid spread argument limits", () => {
  assert.equal(comparisonMetrics(run(Array.from({ length: 160000 }, () => 100))).maxDrawdown, 0);
});
