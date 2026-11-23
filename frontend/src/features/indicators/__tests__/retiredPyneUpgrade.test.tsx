import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { createDefaultChartWorkspaceRecord } from "../../chart-workspace/chartWorkspaceLibrary.js";
import { createChartWorkspaceRepository } from "../../chart-workspace/chartWorkspaceRepository.js";
import type { ChartWorkspaceLibrarySnapshot } from "../../chart-workspace/chartWorkspaceTypes.js";
import { indicatorDefinitionSchema } from "../../app-control/chartCommands.js";
import { indicatorWarmPlanKey } from "../../market-data/manager/chartDataFlowManager.js";
import { applyIndicatorScriptUpdate, loadActiveIndicators } from "../activeIndicatorStore.js";
import IndicatorPanel from "../IndicatorPanel.js";
import { parseCustomIndicatorRecord } from "../indicatorContracts.js";
import { resolveLocalIndicatorExecution } from "../indicatorComputeJobRuntime.js";
import { isWsHostedIndicator } from "../indicatorPayloadRuntime.js";
import { indicatorRuntimeAdapter } from "../indicatorRuntimeAdapter.js";
import type { IndicatorDefinition, IndicatorPreset } from "../indicatorTypes.js";
import { buildHostedSubscriptionMessage, getVisibleHostedIndicators } from "../indicatorWsRuntime.js";
import { isPineScriptSubscription } from "../pineChartTransport.js";
import { isRetiredScriptIndicator, PYNE_RETIRED_ERROR } from "../retiredScriptIndicator.js";
import { providedBarsIndicatorSupport, prepareProvidedBarsIndicator } from "../useProvidedBarsIndicatorRuntime.js";

// Builds before PR #105 (2026-10-26), including the 0.3.0 build of 2026-10-25,
// defaulted chart script indicators to Pyne and left `language` out for them.
// The chart workspace schema (v9) was the same then, so the language-less
// script is the only marker of such an indicator.
const PYNE_SOURCE = "ema = ta.ema(close, 20)\nplot(ema)\n";
const legacyPyne: IndicatorDefinition = {
  id: "custom-legacy0001", name: "My Pyne EMA", engineName: null, script: PYNE_SOURCE,
  params: { length: 20 }, description: "", category: "custom", paneTarget: "main",
  securityMode: "safe", kind: "script", isPreset: false, visible: true,
};
const builtinMa: IndicatorDefinition = {
  id: "ma", name: "MA", engineName: "MA", script: "", params: { period: 20 }, kind: "builtin", isPreset: true, visible: true,
};
const pine: IndicatorDefinition = {
  id: "custom-pine0001", name: "Pine SMA", engineName: null, language: "pine", kind: "script", isPreset: false,
  script: "//@version=6\nindicator(\"SMA\")\nplot(ta.sma(close, 20))", params: {}, securityMode: "safe", visible: true,
};
const context = {
  exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m", chartDataLength: 500,
} as Parameters<typeof buildHostedSubscriptionMessage>[1];

function oldWorkspaceRecord(): unknown {
  const record = JSON.parse(JSON.stringify(createDefaultChartWorkspaceRecord(1_761_000_000_000))) as {
    document: { cells: Record<string, { indicators: IndicatorDefinition[] }> };
  };
  const cell = Object.values(record.document.cells)[0]!;
  cell.indicators = [legacyPyne, builtinMa, pine];
  return record;
}

async function loadOldWorkspace() {
  const raw = oldWorkspaceRecord();
  const stored = JSON.stringify(raw);
  const saved: ChartWorkspaceLibrarySnapshot[] = [];
  const repository = createChartWorkspaceRepository({
    storage: null,
    adapter: {
      loadV7Records: async () => [raw],
      compareAndSwapV7Library: async (snapshot) => {
        saved.push(JSON.parse(JSON.stringify(snapshot)) as ChartWorkspaceLibrarySnapshot);
      },
    },
  });
  const library = await repository.loadLibrary();
  const indicators = Object.values(library.workspaces[0]!.document.cells)[0]!.indicators;
  return { raw, stored, repository, library, indicators, saved };
}

test("an old-format workspace loads its language-less script as retired Pyne and keeps it", async () => {
  const { raw, stored, indicators } = await loadOldWorkspace();
  assert.equal(JSON.stringify(raw), stored, "the stored record is not mutated by loading");
  assert.deepEqual(indicators.map((item) => [item.id, item.language]), [
    ["custom-legacy0001", "pyne"], ["ma", undefined], ["custom-pine0001", "pine"],
  ]);
  const retired = indicators[0]!;
  assert.deepEqual({ ...retired, language: undefined }, { ...legacyPyne, language: undefined },
    "only the explicit language is added; id, script and params are the user's");
  assert.equal(retired.script, PYNE_SOURCE);
  assert.ok(isRetiredScriptIndicator(retired));
  assert.ok(!isRetiredScriptIndicator(indicators[1]) && !isRetiredScriptIndicator(indicators[2]));
});

test("saving the workspace keeps the retired indicator", async () => {
  const { repository, library, saved } = await loadOldWorkspace();
  await repository.saveLibrary(library);
  const cell = Object.values(saved.at(-1)!.workspaces[0]!.document.cells)[0]!;
  const kept = cell.indicators.find((item) => item.id === legacyPyne.id);
  assert.equal(kept?.script, PYNE_SOURCE);
  assert.equal(kept?.language, "pyne");
});

test("the legacy single-chart indicator list loads Pyne the same way", () => {
  const items = new Map([["candlescope-active-indicators", JSON.stringify([legacyPyne, pine])]]);
  const loaded = loadActiveIndicators("candlescope-active-indicators", {
    getItem: (key) => items.get(key) ?? null, setItem: () => assert.fail("loading never writes"),
  });
  assert.deepEqual(loaded.map((item) => item.language), ["pyne", "pine"]);
});

test("a retired script never reaches a runtime, hosted or local", async () => {
  const { indicators } = await loadOldWorkspace();
  const retired = indicators[0]!;
  for (const candidate of [retired, legacyPyne, { ...retired, executionTarget: "local" as const }, { ...legacyPyne, kind: "pyne" }]) {
    assert.deepEqual(resolveLocalIndicatorExecution(candidate), { kind: "invalid", error: PYNE_RETIRED_ERROR });
    assert.equal(isWsHostedIndicator(candidate), false);
    assert.equal(indicatorRuntimeAdapter(candidate, {}).runtime, "retired");
    assert.equal(providedBarsIndicatorSupport(candidate).supported, false);
    assert.equal(prepareProvidedBarsIndicator(candidate), null);
  }
  assert.deepEqual(getVisibleHostedIndicators(indicators).map((item) => item.id), ["ma", "custom-pine0001"]);
  const warm = JSON.parse(indicatorWarmPlanKey({ indicators, candleUpColor: "#0f0", candleDownColor: "#f00" })) as unknown;
  assert.doesNotMatch(JSON.stringify(warm), /custom-legacy0001/);
});

test("an edit never relabels the retired source as another language", () => {
  const retired = { ...legacyPyne, language: "pyne" };
  assert.equal(applyIndicatorScriptUpdate(retired, "plot(close)", "pine"), retired);
  assert.equal(applyIndicatorScriptUpdate(legacyPyne, PYNE_SOURCE, "pine"), legacyPyne);
});

test("a new Pine indicator still runs as Pine", async () => {
  const { indicators } = await loadOldWorkspace();
  const current = indicators[2]!;
  assert.deepEqual(resolveLocalIndicatorExecution(current), { kind: "hosted" });
  assert.equal(isWsHostedIndicator(current), true);
  assert.equal(indicatorRuntimeAdapter(current, {}).runtime, "pine");
  const message = buildHostedSubscriptionMessage(current, context);
  assert.equal(message.kind, "script");
  assert.equal(message.language, "pine");
  assert.equal(isPineScriptSubscription(message), true);
  const local = resolveLocalIndicatorExecution({ ...current, executionTarget: "local" });
  assert.equal(local.kind, "local");
  assert.equal(providedBarsIndicatorSupport(current).supported, true);
  assert.equal(prepareProvidedBarsIndicator(current)?.language, "pine");
});

test("a subscription without a language is not Pine", () => {
  assert.equal(isPineScriptSubscription({ kind: "script" }), false);
  assert.equal(isPineScriptSubscription({ kind: "script", language: "pine" }), true);
});

test("a saved custom record without a language lists as retired Pyne", () => {
  const legacy = parseCustomIndicatorRecord({
    schemaVersion: 1, id: "custom-0123456789ab", kind: "script", name: "Old", description: "",
    script: PYNE_SOURCE, params: {}, paramSchema: [], renderHints: {}, securityMode: "safe",
  });
  assert.deepEqual([legacy.language, legacy.retired], ["pyne", true]);
  const listed = parseCustomIndicatorRecord({ ...legacy, language: "pyne", retired: true });
  assert.deepEqual([listed.language, listed.retired], ["pyne", true]);
  const current = parseCustomIndicatorRecord({ ...legacy, language: "pine", retired: false });
  assert.deepEqual([current.language, current.retired], ["pine", false]);
});

test("control-added scripts must name their language", () => {
  assert.throws(() => indicatorDefinitionSchema.parse({ id: "x", name: "X", kind: "script", script: "plot(close)" }),
    /INDICATOR_LANGUAGE_REQUIRED/);
  assert.equal(indicatorDefinitionSchema.parse({ id: "ma", name: "MA", engineName: "MA", kind: "builtin" }).language, undefined);
  assert.equal(indicatorDefinitionSchema.parse({ id: "p", name: "P", kind: "script", script: "plot(close)", language: "pine" }).language, "pine");
});

function panel(props: Partial<React.ComponentProps<typeof IndicatorPanel>>) {
  return renderToStaticMarkup(<IndicatorPanel isOpen onClose={() => undefined}
    staticCatalog={{ presets: [], resolvePresetForChart: (item) => item as IndicatorPreset }}
    activeIndicators={[]} onAddIndicator={() => assert.fail("a retired script is never added")}
    onRemoveIndicator={() => undefined} onToggleVisibility={() => undefined}
    onUpdateParams={() => undefined} onUpdateScript={() => assert.fail("a retired script is never edited")}
    computing={false} {...props} />);
}

test("the Added tab shows a retired script as retired, with no edit and no Pine label", async () => {
  const { indicators } = await loadOldWorkspace();
  const html = panel({ initialTab: "active", activeIndicators: indicators });
  const row = /<li[^>]*data-retired="true"[^]*?<\/li>/.exec(html)?.[0] ?? "";
  assert.match(row, /My Pyne EMA/);
  assert.match(row, /已退役/, "the retired badge");
  assert.match(row, /Pyne 已退役。此已保存的脚本保持不变，但不会运行，也不会被当作 Pine。/);
  assert.match(row, /<button[^>]*aria-label="Pyne 已退役[^"]*"[^>]*disabled=""/, "editing is disabled");
  assert.doesNotMatch(row, /indicator-params/, "its saved params are kept, not offered for editing");
  assert.doesNotMatch(row, /PYNE_RETIRED/, "the raw error code is not shown");
  assert.equal((html.match(/data-retired="true"/g) ?? []).length, 1, "the Pine and builtin rows are not retired");
});

test("the library shows a retired saved script as retired and cannot add it", () => {
  const record = { ...parseCustomIndicatorRecord({
    schemaVersion: 1, id: "custom-0123456789ab", kind: "script", name: "Old Pyne", description: "",
    script: PYNE_SOURCE, params: {}, paramSchema: [], renderHints: {},
  }), category: "custom", is_builtin: false, isPreset: false, paneTarget: "sub" } as unknown as IndicatorPreset;
  const html = panel({ staticCatalog: { presets: [record], resolvePresetForChart: (item) => item as IndicatorPreset } });
  const row = /<li[^>]*data-indicator-id="custom-0123456789ab"[^]*?<\/li>/.exec(html)?.[0] ?? "";
  assert.match(row, /data-retired="true"/);
  assert.match(row, /已退役/);
  assert.match(row, /<button[^>]*class="[^"]*indicator-add-btn[^"]*"[^>]*disabled=""/, "add to chart is disabled");
});
