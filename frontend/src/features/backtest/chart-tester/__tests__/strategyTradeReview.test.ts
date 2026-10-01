import assert from "node:assert/strict";
import test from "node:test";
import { strategyTradeFocus, strategyTradeRange } from "../strategyTradeReview.js";
import { SeriesWindowStore } from "../../../market-data/window/seriesWindowStore.js";
import { createChartStrategyResultMarkerSource } from "../chartStrategyResultMarkerSource.js";
test("normalizes seconds and milliseconds without inventing fill exits", () => {
  assert.deepEqual(strategyTradeFocus({ entryTime: 60, exitTime: 120 }, "a"), strategyTradeFocus({ entry_time_ms: "60000", exit_time_ms: "120000" }, "a"));
  assert.equal(strategyTradeFocus({ event_time_ms: 60000 }, "fill")?.exitTimeMs, null);
  assert.equal(strategyTradeFocus({ entryTime: null }, "missing"), null);
  assert.equal(strategyTradeFocus({ entryTime: 120, exitTime: 60 }, "bad")?.exitTimeMs, null);
});
test("review framing includes both endpoints and surrounding candles", () => {
  assert.deepEqual(strategyTradeRange(strategyTradeFocus({ entryTime: 600, exitTime: 660 }, "a")!, 60), { from: 120, to: 1140 });
  assert.deepEqual(strategyTradeRange(strategyTradeFocus({ entryTime: 600, exitTime: 6600 }, "a")!, 60), { from: -900, to: 8100 });
});
test("review markers align to loaded candles, update with history, and clear without a host run", () => {
  const seriesStore = new SeriesWindowStore({ maxBars: 100, intervalSeconds: 60 });
  const bar = (time: number) => ({ time, open: 100, high: 101, low: 99, close: 100, volume: 1 });
  seriesStore.replace([bar(60)]);
  const source = createChartStrategyResultMarkerSource({ seriesStore, labels: { actions: { OPEN_LONG: "open" }, rejection: "rejected" } });
  source.setTradeFocus({ id: "a", entryTimeMs: 61000, exitTimeMs: 121000, entryPrice: 100, exitPrice: 101 }, "1m", "Entry", "Exit");
  assert.deepEqual(source.getSnapshot().markers.map((marker) => marker.time), [60]);
  seriesStore.replace([bar(60), bar(120)]);
  assert.deepEqual(source.getSnapshot().markers.map((marker) => marker.time), [60, 120]);
  assert.equal(source.getSnapshot().markers[1]?.text, "Exit 101");
  source.setTradeFocus(null, "1m", "Entry", "Exit");
  assert.equal(source.getSnapshot().markers.length, 0);
  source.setTradeFocus({ id: "open", entryTimeMs: 61000, exitTimeMs: null, entryPrice: null, exitPrice: null }, "1m", "Entry", "Exit");
  assert.equal(source.getSnapshot().markers.length, 1);
  source.clear();
  assert.equal(source.getSnapshot().markers.length, 0);
  source.dispose();
});
