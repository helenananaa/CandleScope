import assert from "node:assert/strict";
import test from "node:test";
import { strategySourceParameters, replaceStrategySourceParameter } from "../strategySourceParameters.js";
import { validExecutionOverrides, validStrategyRunSettings } from "../../../../shared/strategyRunSettings.js";

test("parameter fields edit actual literals and never replace comments, expressions or changed source", () => {
  const source = '# fast = sma(close, 3)\nfast = sma(close, 3)\nslow = sma(close, fast + 2)\nif value < 30\n  target_position(1)';
  const fields = strategySourceParameters(source);
  assert.equal(fields.length, 3);
  const changed = replaceStrategySourceParameter(source, fields[0]!, "8");
  assert.ok(changed.includes('fast = sma(close, 8)'));
  assert.ok(changed.startsWith('# fast = sma(close, 3)'));
  assert.equal(replaceStrategySourceParameter(changed, fields[0]!, "9"), changed);
  assert.equal(replaceStrategySourceParameter(source, fields[0]!, "0"), source);
});

test("run settings reject invalid ranges and nonfinite or out-of-range account values", () => {
  const execution = { initialBalance: "2000", equityPercent: "25", leverage: "2", feeBps: "5", slippageBps: "2" };
  assert.ok(validExecutionOverrides(execution));
  assert.equal(validExecutionOverrides({ ...execution, initialBalance: "0" }), false);
  assert.equal(validExecutionOverrides({ ...execution, feeBps: "NaN" }), false);
  assert.equal(validExecutionOverrides({ ...execution, equityPercent: "101" }), false);
  assert.ok(validStrategyRunSettings({ rangeMode: "CUSTOM", customRange: { startMs: 1000, endMs: 2000 }, executionOverrides: execution }));
  assert.equal(validStrategyRunSettings({ rangeMode: "CUSTOM", customRange: { startMs: 2000, endMs: 1000 } }), false);
});
