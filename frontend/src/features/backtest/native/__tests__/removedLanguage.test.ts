import assert from "node:assert/strict";
import test from "node:test";
import { normalizeNativeStrategies } from "../nativeStrategyCollection.js";
import { prepareProvidedBarsIndicator } from "../../../indicators/useProvidedBarsIndicatorRuntime.js";
import { CHART_STRATEGY_TEMPLATES } from "../../chart-tester/chartStrategyTesterUiModel.js";

test("removed native scripts never become Pine when a workspace is restored", () => {
  const restored = normalizeNativeStrategies({ activeId: "old", items: [
    { id: "old", language: "pyne", drafts: { source: "strategy.entry_when(close > 1)" } },
    { id: "kept", language: "pine", drafts: { source: "//@version=6\nstrategy('Pine')" } },
  ] });
  assert.deepEqual(restored.items.map((item) => item.id), ["kept"]);
  assert.equal(restored.activeId, "kept");
  assert.equal(restored.items[0]?.drafts.source, "//@version=6\nstrategy('Pine')");
});

test("provided-bars indicators and new strategy templates exclude the retired language", () => {
  assert.equal(prepareProvidedBarsIndicator({ id: "old", name: "old", kind: "script", language: "pyne", script: "plot(close)" }), null);
  assert.ok(prepareProvidedBarsIndicator({ id: "pine", name: "pine", kind: "script", language: "pine", script: "plot(close)" }));
  assert.ok(CHART_STRATEGY_TEMPLATES.length > 0);
  assert.ok(CHART_STRATEGY_TEMPLATES.every((item) => item.language === "python" || item.language === "pine"));
});
