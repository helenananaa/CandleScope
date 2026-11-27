import assert from "node:assert/strict";
import test from "node:test";

import { ChartStrategyChartDataGate, chartStrategyChartDataReady } from "../chartStrategyChartData.js";

const eth5m = { symbol: "ETHUSDT", interval: "5m" };

test("a switched chart is ready only once it commits the new session's first window (RC 34)", () => {
  // The render that switches the session still holds the previous market's committed bars.
  assert.equal(chartStrategyChartDataReady({ barCount: 500, loading: false, initialHistoryPending: false,
    meta: { symbol: "BTCUSDT", interval: "1m" } }, eth5m), false);
  // The transition: loading, optimistic, nothing of the new series yet.
  assert.equal(chartStrategyChartDataReady({ barCount: 0, loading: true, initialHistoryPending: true,
    meta: { symbol: "BTCUSDT", interval: "1m", optimistic: true } }, eth5m), false);
  assert.equal(chartStrategyChartDataReady({ barCount: 500, loading: false, initialHistoryPending: false,
    meta: { symbol: "ETHUSDT", interval: "5m", optimistic: true } }, eth5m), false);
  assert.equal(chartStrategyChartDataReady({ barCount: 500, loading: false, initialHistoryPending: true,
    meta: { symbol: "ETHUSDT", interval: "5m" } }, eth5m), false);
  assert.equal(chartStrategyChartDataReady({ barCount: 500, loading: false, initialHistoryPending: false,
    meta: { symbol: "ETHUSDT", interval: "5m" } }, eth5m), true);
});

test("the chart data gate releases waiting runs when ready and drops aborted ones", async () => {
  const gate = new ChartStrategyChartDataGate(false);
  let released = 0;
  const first = gate.wait().then(() => { released += 1; });
  const controller = new AbortController();
  const stopped = gate.wait(controller.signal);
  controller.abort(new DOMException("stopped", "AbortError"));
  await assert.rejects(stopped, { name: "AbortError" });
  await Promise.resolve();
  assert.equal(released, 0);
  gate.set(true);
  await first;
  assert.equal(released, 1);
  await gate.wait();
  gate.set(false);
  const aborted = new AbortController();
  aborted.abort(new DOMException("gone", "AbortError"));
  await assert.rejects(gate.wait(aborted.signal), { name: "AbortError" });
});
