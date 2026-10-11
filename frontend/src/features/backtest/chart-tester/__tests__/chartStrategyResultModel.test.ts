import assert from "node:assert/strict";
import test from "node:test";

import {
  chartStrategyResultIncludedInExportScope,
  chartStrategyTradeFocusTimeMs,
  chartStrategyVirtualTradeWindow,
  chartStrategyWinRate,
  chartStrategyMaxDrawdown,
  chartStrategyDrawdownDetailKey,
  sampledReportDrawdown,
} from "../chartStrategyResultModel.js";
import type { BacktestReport } from "../../backtestTypes.js";

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

test("legacy reports compute drawdown from all equity samples, including intraday recovery", () => {
  const report = { account: { initial_balance: "100" }, equity_curve: [
    { event_time_ms: 1, equity: "90" }, { event_time_ms: 2, equity: "120" },
    { event_time_ms: 3, equity: "60" }, { event_time_ms: 4, equity: "120" },
  ] } as unknown as BacktestReport;
  assert.equal(sampledReportDrawdown(report)?.maximum, 0.5);
  assert.equal(chartStrategyMaxDrawdown(report), "50.00%");
  assert.equal(chartStrategyDrawdownDetailKey(report), "chartTester.result.drawdownBasis");
  assert.equal(sampledReportDrawdown(report)?.curve[0]?.drawdown, "-0.1");
  report.equity_curve = [{ event_time_ms: 1, equity: "100" }, { event_time_ms: 2, equity: "110" }];
  assert.equal(chartStrategyMaxDrawdown(report), "0.00%");
  report.performance = { risk: { max_drawdown: { value: "0.125", reason: null } } } as unknown as NonNullable<BacktestReport["performance"]>;
  assert.equal(chartStrategyMaxDrawdown(report), "12.50%");
  report.performance.risk.max_drawdown = { value: null, reason: "INSUFFICIENT_EQUITY_SAMPLES" };
  assert.equal(chartStrategyMaxDrawdown(report), "—");
  assert.equal(chartStrategyDrawdownDetailKey(report), "chartTester.result.drawdownSamples");
});

test("invalid or insufficient legacy equity never becomes a false zero drawdown", () => {
  for (const equity_curve of [[], [{ event_time_ms: 1, equity: "100" }],
    [{ event_time_ms: 1, equity: "bad" }, { event_time_ms: 2, equity: "90" }],
    [{ event_time_ms: 1, equity: "0" }, { event_time_ms: 2, equity: "0" }]]) {
    assert.equal(chartStrategyMaxDrawdown({ equity_curve } as unknown as BacktestReport), "—");
  }
});
