import assert from "node:assert/strict";
import test from "node:test";
import { normalizeComparison, recordStrategyRun, strategyRunIds, copyNativeStrategy, normalizeNativeStrategies, strategyInstanceScope } from "../nativeStrategyCollection.js";

test("old charts keep their existing draft scope while new instances are isolated", () => {
  const migrated = normalizeNativeStrategies(undefined);
  assert.equal(strategyInstanceScope("workspace\0cell", migrated.activeId), "workspace\0cell");
  assert.notEqual(strategyInstanceScope("workspace\0cell", "second"), "workspace\0cell");
});
test("copy carries independent inputs without claiming the original execution result", () => {
  const original = { id: "a", name: "SMA", language: "pine" as const, drafts: { "pine:NATIVE": JSON.stringify({ parameters: JSON.stringify({ fast: 5 }) }) }, runs: { btc: "run-a" } };
  const copy = copyNativeStrategy(original, "b", "SMA copy");
  assert.deepEqual(copy.drafts, original.drafts);
  copy.drafts["pine:NATIVE"] = "changed";
  assert.notEqual(copy.drafts["pine:NATIVE"], original.drafts["pine:NATIVE"]);
  assert.deepEqual(copy.runs, {});
});
test("workspace restore rejects duplicate IDs and selects an existing strategy", () => {
  const restored = normalizeNativeStrategies({ activeId: "missing", items: [{ id: "a", drafts: { good: "saved", invalid: 3 } }, { id: "a" }, null] });
  assert.equal(restored.activeId, "a");
  assert.equal(restored.items.length, 1);
  assert.deepEqual(restored.items[0]?.drafts, { good: "saved" });
  assert.equal(normalizeNativeStrategies(JSON.parse(JSON.stringify(restored))).activeId, "a");
});


test("explicitly removing all strategies does not resurrect a legacy draft", () => {
  assert.deepEqual(normalizeNativeStrategies({ activeId: "removed", items: [] }), { activeId: "", items: [] });
});


test("comparison pins and names survive workspace normalization, including removed instances", () => {
  const comparison = { name: "Trend comparison", metric: "drawdownPct" as const, pinned: [{ id: "removed", name: "Previous", runId: "fixed-run", mode: "NATIVE" as const }] };
  const restored = normalizeNativeStrategies(JSON.parse(JSON.stringify({ items: [], comparisons: { btc: comparison } })));
  assert.deepEqual(restored.comparisons?.btc, comparison);
  assert.equal(normalizeComparison({ pinned: [{ id: "a", runId: "bad", mode: "invalid" }] }).pinned.length, 0);
});
test("successive runs preserve ownership and copies cannot inherit execution history", () => {
  const context = JSON.stringify(["NATIVE", "binance", "spot", "BTCUSDT", "1h"]);
  const original = { id: "a", name: "A", language: "pine" as const, drafts: {}, runs: { [context]: "old" } };
  const recorded = { ...original, ...recordStrategyRun(original, context, "new") };
  assert.deepEqual([...strategyRunIds(recorded, "NATIVE")].sort(), ["new", "old"]);
  assert.equal(strategyRunIds(recorded, "CANDLESCOPE").size, 0);
  assert.equal(strategyRunIds(copyNativeStrategy(recorded, "b", "B"), "NATIVE").size, 0);
  assert.deepEqual(recordStrategyRun(recorded, context, "new").runHistory?.[context], ["new", "old"]);
});
