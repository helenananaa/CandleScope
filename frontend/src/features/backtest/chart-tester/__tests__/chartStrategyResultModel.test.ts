import assert from "node:assert/strict";
import test from "node:test";

import {
  chartStrategyResultIncludedInExportScope,
  chartStrategyTradeFocusTimeMs,
  chartStrategyVirtualTradeWindow,
  chartStrategyWinRate,
} from "../chartStrategyResultModel.js";

test("win rate renders the backend fraction as a percentage and preserves unavailable metrics", () => {
  assert.equal(chartStrategyWinRate("1", "en"), "100%");
  assert.equal(chartStrategyWinRate("0.125", "en"), "12.5%");
  assert.equal(chartStrategyWinRate({ value: null, reason: "NO_CLOSED_TRADES" }, "en"), "—");
  assert.equal(chartStrategyWinRate({ value: "0.5" }, "en"), "50%");
  assert.equal(chartStrategyWinRate("25%", "en"), "25%");
  assert.equal(chartStrategyWinRate("unknown", "en"), "—");
});

test("100k trade virtualization keeps the rendered window bounded", () => {
  const first = chartStrategyVirtualTradeWindow({
    count: 100_000,
    scrollTop: 0,
    viewportHeight: 304,
  });
  const middle = chartStrategyVirtualTradeWindow({
    count: 100_000,
    scrollTop: 1_900_000,
    viewportHeight: 304,
  });
  assert.equal(first.totalHeight, 3_800_000);
  assert.ok(first.end - first.start <= 20);
  assert.ok(middle.end - middle.start <= 20);
  assert.ok(middle.start > 49_000);
});

test("trade focus uses entry time and screenshot export includes results only for page scope", () => {
  assert.equal(chartStrategyTradeFocusTimeMs({ entry_time_ms: "1700000000123" }), 1_700_000_000_123);
  assert.equal(chartStrategyTradeFocusTimeMs({ entry_time_ms: "invalid" }), null);
  assert.equal(chartStrategyResultIncludedInExportScope("chart"), false);
  assert.equal(chartStrategyResultIncludedInExportScope("main-pane"), false);
  assert.equal(chartStrategyResultIncludedInExportScope("page"), true);
});
