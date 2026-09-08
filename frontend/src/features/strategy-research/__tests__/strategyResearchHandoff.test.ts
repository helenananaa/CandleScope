import assert from "node:assert/strict";
import test from "node:test";
import { saveResearchHandoff, readResearchHandoff } from "../strategyResearchHandoff.js";
import { StrategyResearchRuntime } from "../StrategyResearchRuntime.js";

test("handoff keeps the exact chart, draft, parameters and conditions without granting offline networking", () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage: {
    setItem(key: string, value: string) { values.set(key, value); }, getItem(key: string) { return values.get(key) ?? null; },
  } } });
  try {
    const href = saveResearchHandoff({ session: { exchange: "binance", marketType: "futures", symbol: "ETHUSDT", interval: "15m" }, workspaceId: "workspace-main", cellId: "cell-1", runId: null,
      attachment: { schemaVersion: 1, strategyDraftId: "draft-12345678", strategyRevisionId: null, displayName: "SMA", language: "pyne", parameters: { fast: 8 }, rangeMode: "CUSTOM", customRange: { startMs: 1000, endMs: 2000 }, fidelityPreference: "PRECISE", quickPresetId: "CRYPTO_PERP_STANDARD_V1", autoRun: false,
        executionOverrides: { initialBalance: "3500", equityPercent: "10", leverage: "2", feeBps: "5", slippageBps: "1" } } });
    const id = new URL(href, "http://localhost").searchParams.get("handoff")!;
    const restored = readResearchHandoff(id)!;
    assert.equal(restored.source.symbol, "ETHUSDT");
    assert.equal(restored.source.interval, "15m");
    assert.equal(restored.draftId, "draft-12345678");
    assert.deepEqual(restored.configuration.parameters, { fast: 8 });
    assert.equal(restored.configuration.executionOverrides?.initialBalance, "3500");
    assert.equal(restored.configuration.fidelityPreference, "PRECISE");
    const live = new StrategyResearchRuntime({ restoreWorkspace: false, runtimeMode: "LIVE" });
    live.dispatch({ type: "source/select", source: restored.source });
    assert.equal(live.currentChartRunnable(), true);
    const offline = new StrategyResearchRuntime({ restoreWorkspace: false, runtimeMode: "LOCAL_OFFLINE" });
    offline.dispatch({ type: "source/select", source: restored.source });
    assert.equal(offline.currentChartRunnable(), false);
    assert.equal(readResearchHandoff("missing-context"), null);
    assert.equal(readResearchHandoff("../invalid"), null);
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
