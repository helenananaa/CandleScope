import assert from "node:assert/strict";
import test from "node:test";
import { reportAnalytics, reportNumber, reportTrade } from "../nativeReportAnalytics.js";
import type { NativeResult } from "../nativeBacktestApi.js";

const result = (patch: Partial<NativeResult> = {}): NativeResult => ({ account_authority: "native", fill_model: "test", report_hash: "test", equity: [], bars: [], trades: [], orders: [], graphics: [], raw_output: {}, diagnostics: [], ...patch });
const trade = (profit: unknown) => ({ entryTime: 1, exitTime: 2, entryPrice: 100, exitPrice: 110, profit });

test("report distinguishes sampled equity change from closed-trade profit", () => {
  const data = reportAnalytics(result({ equity: [{ time: 3, value: 90 }, { time: 1, value: 100 }, { time: 2, value: 120 }], trades: [trade(20), trade(-5), trade(0), { entryTime: 2, profit: 999 }] }));
  assert.equal(data.equityChange, -10);
  assert.equal(data.netProfit, 15);
  assert.equal(data.maxDrawdown, 30);
  assert.equal(data.maxDrawdownPercent, 25);
  assert.equal(data.closedCount, 3);
  assert.ok(Math.abs(data.winRate! - 100 / 3) < 1e-10);
  assert.equal(data.profitFactor, 4);
});
test("missing profits and external fill rows do not become zero or closed-trade statistics", () => {
  const incomplete = reportAnalytics(result({ trades: [trade(5), trade(null)] }));
  assert.equal(incomplete.netProfit, null);
  assert.equal(incomplete.winRate, null);
  assert.equal(incomplete.profitFactor, null);
  assert.equal(reportAnalytics(result({ trades: [trade(5)] }), true).closedCount, 0);
  assert.equal(reportAnalytics(result()).maxDrawdown, null);
  assert.equal(reportNumber(false), null);
  assert.equal(reportNumber(""), null);
  assert.equal(reportNumber(0), 0);
});
test("profit factor handles no losses and all-zero trades explicitly", () => {
  assert.equal(reportAnalytics(result({ trades: [trade(5)] })).profitFactor, Infinity);
  assert.equal(reportAnalytics(result({ trades: [trade(0)] })).profitFactor, null);
  assert.equal(reportAnalytics(result({ trades: [trade(-5)] })).profitFactor, 0);
});
test("benchmark excludes future bars and normalizes only available report window", () => {
  const data = reportAnalytics(result({ equity: [{ time: 2, value: 0 }, { time: 3, value: 10 }], bars: [1, 2, 3, 4].map(time => ({ time, open: 1, high: 1, low: 1, close: time * 100 })) }));
  assert.deepEqual(data.benchmark, [{ time: 2, value: 0 }, { time: 3, value: 50 }]);
  assert.equal(data.series[1]!.returnPercent, null);
});
test("trade view does not infer direction from IDs or manufacture percentage returns", () => {
  const data = reportTrade({ ...trade(5), id: "L" });
  assert.equal(data.side, null);
  assert.equal(data.returnPercent, null);
  assert.equal(data.duration, 1000);
  assert.equal(reportTrade({ ...trade(5), direction: "strategy.short" }).side, "short");
});
