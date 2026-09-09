import assert from "node:assert/strict";
import test from "node:test";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import { parseReplayDisplayBar } from "../replayParser.js";
import { replayDisplayBarToKline } from "../replaySeriesProjection.js";
import { applyReplayViewerServerTail } from "../replayViewerProjection.js";

function bar(index: number) {
  const open = 1_700_000_000_000 + index * 900_000;
  return parseReplayDisplayBar({
    open_time_ms: open, close_time_ms: open + 899_999,
    open: "100", high: "102", low: "99", close: "101", volume: "15",
    quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
    first_base_open_ms: open, last_base_open_ms: open + 840_000,
    component_count: 15, expected_components: 15, is_closed: true, synthetic: false,
  }, "test bar");
}

test("server tail preserves history and emits an append, not a replacement", () => {
  const store = new SeriesWindowStore();
  store.replace([bar(0), bar(1)].map(replayDisplayBarToKline));
  const first = store.first();
  const changes: string[] = [];
  store.subscribe((delta) => changes.push(delta.type));
  assert.equal(applyReplayViewerServerTail(store, [bar(1), bar(2)], bar(1).close_time_ms, bar(2).close_time_ms), true);
  assert.equal(store.barCount, 3);
  assert.strictEqual(store.first(), first);
  assert.ok(!changes.includes("replace"));
});

test("missing overlap, future bars and rewind require full projection recovery", () => {
  const store = new SeriesWindowStore();
  store.replace([bar(0)].map(replayDisplayBarToKline));
  const original = store.snapshot();
  assert.equal(applyReplayViewerServerTail(store, [bar(2)], bar(0).close_time_ms, bar(2).close_time_ms), false);
  assert.equal(applyReplayViewerServerTail(store, [bar(0), bar(1)], bar(0).close_time_ms, bar(0).close_time_ms), false);
  assert.equal(applyReplayViewerServerTail(store, [bar(0)], bar(1).close_time_ms, bar(0).close_time_ms), false);
  assert.deepEqual(store.snapshot(), original);
});
