import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StorageMaintenancePanel from "../StorageMaintenancePanel.js";
import { getLocale, setLocale } from "../../../i18n/index.js";
import type { MaintenanceResult } from "../../../features/settings/maintenanceSettingsRuntime.js";

function render(result: MaintenanceResult) {
  return renderToStaticMarkup(<StorageMaintenancePanel
    currentSymbol="BTCUSDT" currentMarketType="spot" currentExchange="binance"
    currentScopeSymbols={["BTCUSDT"]} watchlistScopeSymbols={["BTCUSDT", "ETHUSDT"]}
    storageRepairLoading={false} storageRepairResult={null}
    gapScanLoading={false} gapScanResult={result} maintenanceScope="current"
    exchangeRefreshLoading={false} exchangeRefreshResult={null}
    onStorageRepair={() => {}} onGapScan={() => {}} onExchangeRefresh={() => {}}
  />);
}

test("gap inspection shows symbols, actual UTC bounds, unknown coverage and continuation", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const html = render({ status: "partial", has_more: true, scanned_ranges: 1, verified_ranges: 1,
      results: [
        { symbol: "BTCUSDT", interval: "1m", status: "ok", lane: "interior",
          scanned_from_ms: 0, scanned_to_ms: 60_000, truncated: true, next_cursor_ms: 120_000, remaining_gaps: 0 },
        { symbol: "ETHUSDT", interval: "1m", status: "error", repair_errors: ["source unavailable"] },
      ], errors: ["inventory warning"],
    });
    assert.ok(html.includes("BTCUSDT"));
    assert.ok(html.includes("ETHUSDT"));
    assert.ok(html.includes("Inspected range: 1970-01-01 00:00:00 — 1970-01-01 00:01:00 (UTC)"));
    assert.ok(html.includes("Continue from 1970-01-01 00:02:00 (UTC)"));
    assert.ok(html.includes("Continue checking"));
    assert.ok(html.includes("Remaining gaps: Unknown"));
    assert.ok(html.includes("source unavailable"));
    assert.ok(html.includes("inventory warning"));
    assert.ok(html.includes("st-result-warn"));
    assert.ok(!html.includes("st-result-ok"));
  } finally { setLocale(previous); }
});

test("empty inspection has no success styling or invented gap count", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const html = render({ status: "empty", results: [] });
    assert.ok(html.includes("st-result-warn"));
    assert.ok(!html.includes("st-result-ok"));
    assert.ok(!html.includes("Remaining gaps: 0"));
  } finally { setLocale(previous); }
});
