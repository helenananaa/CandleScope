import assert from "node:assert/strict";
import test from "node:test";

import {
  createLocalIndicatorDefinition,
  LOCAL_INDICATOR_PRESETS,
  normalizeLocalIndicatorDefinition,
} from "./localIndicatorCatalog.js";


test("local indicator catalog supports multiple instances of one builtin", () => {
  const first = createLocalIndicatorDefinition("MA");
  const second = createLocalIndicatorDefinition("MA");

  assert.notEqual(first.id, second.id);
  assert.equal(first.executionTarget, "local");
  assert.equal(first.engineName, "MA");
});

test("the shared indicator panel receives only the five local static presets", () => {
  assert.deepEqual(
    LOCAL_INDICATOR_PRESETS.map((preset) => preset.engineName),
    ["MA", "EMA", "RSI", "MACD", "BOLL"],
  );
  assert.equal(LOCAL_INDICATOR_PRESETS.every((preset) => (
    preset.executionTarget === "local" && preset.is_builtin
  )), true);
});

test("persisted local indicator definitions are fail-closed and parameter bounded", () => {
  const normalized = normalizeLocalIndicatorDefinition({
    id: "local-ma-saved",
    engineName: "MA",
    executionTarget: "hosted",
    params: { period: 0, source: "volume", color: "bad", extra: 12 },
  });

  assert.deepEqual(normalized?.params, {
    period: 20,
    source: "close",
    color: "#f59e0b",
  });
  assert.equal(normalized?.executionTarget, "local");
  assert.equal(normalizeLocalIndicatorDefinition({
    id: "foreign-indicator",
    engineName: "MA",
  }), null);
  assert.equal(normalizeLocalIndicatorDefinition({
    id: "local-script-one",
    engineName: "CUSTOM",
  }), null);
});
