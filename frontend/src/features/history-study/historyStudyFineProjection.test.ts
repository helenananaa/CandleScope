import assert from "node:assert/strict";
import test from "node:test";
import { HistoryStudyPlayback } from "./historyStudyPlayback.js";
import type { HistoryStudy } from "./historyStudyTypes.js";
import { WINDOW_DELTA_TYPES } from "../market-data/klineContracts.js";

function study(): HistoryStudy {
  const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "5m" };
  return { id: "fine-study", capturedAtMs: 10_000_000, inputKind: "captured-market-history", series,
    sourceSeries: { ...series, interval: "1m" }, rows: Array.from({ length: 20 }, (_, i) => ({
      time: i * 60, closeTimeMs: (i + 1) * 60_000, open: 100 + i, high: 110 + i,
      low: 90 + i, close: 105 + i, volume: i + 1, is_closed: true,
      quote_volume: 2 * (i + 1), trades: i + 1, taker_buy_base: (i + 1) / 2,
    })) };
}

test("forming display OHLCV uses only closed finer input, and intrabar time never reveals a final source candle", () => {
  const input = study(), playback = new HistoryStudyPlayback(input, 390_000);
  const rows = playback.store.snapshot();
  assert.equal(rows.length, 2);
  assert.deepEqual([rows[0]!.open, rows[0]!.high, rows[0]!.low, rows[0]!.close, rows[0]!.volume], [100, 114, 90, 109, 15]);
  assert.equal(rows[0]!.is_closed, true);
  assert.deepEqual([rows[1]!.open, rows[1]!.high, rows[1]!.low, rows[1]!.close, rows[1]!.volume], [105, 115, 95, 110, 6]);
  assert.equal(rows[1]!.is_closed, false);
  assert.equal(rows[1]!.quote_volume, 12);
  assert.equal(rows[1]!.taker_buy_base, 3);
  const before = playback.store.snapshot();
  playback.seek(419_999);
  assert.equal(playback.store.snapshot(), before);
  assert.equal(playback.step(1), 420_000);
  assert.equal(playback.store.last()!.high, 116);
  assert.equal(playback.store.first()!.high, 114);
  assert.equal(input.rows[6]!.high, 116);
});

test("forward admits only the affected display tail; rewind and restart reproduce the same smaller prefix", () => {
  const input = study(), playback = new HistoryStudyPlayback(input, 300_000);
  const deltas: string[] = [];
  playback.store.subscribe(delta => deltas.push(delta.type));
  playback.seek(660_000);
  assert.equal(playback.store.barCount, 3);
  assert.equal(deltas.includes(WINDOW_DELTA_TYPES.REPLACE), false, "ordinary forward steps merge the tail rather than replacing all history");
  assert.ok(deltas.length > 0);
  playback.seek(450_000);
  const expected = new HistoryStudyPlayback(input, 450_000);
  assert.deepEqual(playback.store.snapshot(), expected.store.snapshot());
  assert.equal(playback.store.last()!.high, 116);
  assert.equal(playback.store.last()!.volume, 13);
  const restarted = new HistoryStudyPlayback(JSON.parse(JSON.stringify(input)) as HistoryStudy, playback.cursorMs);
  assert.deepEqual(restarted.store.snapshot(), expected.store.snapshot());
});

test("a newly revealed internal gap removes an earlier partial candle, and rewind restores the earlier valid view", () => {
  const input = study(); input.rows = input.rows.filter(row => row.time !== 120);
  const playback = new HistoryStudyPlayback(input, 120_000);
  assert.equal(playback.store.barCount, 1);
  playback.seek(240_000);
  assert.equal(playback.store.barCount, 0);
  assert.deepEqual(playback.missingBuckets, [0]);
  playback.seek(420_000);
  assert.deepEqual(playback.store.snapshot().map(row => row.time), [300]);
  assert.equal(playback.store.last()!.is_closed, false);
  playback.seek(120_000);
  assert.deepEqual(playback.missingBuckets, []);
  assert.deepEqual(playback.store.snapshot().map(row => row.time), [0]);
  const missingStart = study(); missingStart.rows = missingStart.rows.slice(1);
  assert.equal(new HistoryStudyPlayback(missingStart, 300_000).store.barCount, 0);
});

test("calendar month reconstruction follows real leap-month boundaries rather than a fixed number of days", () => {
  const start = Date.UTC(2024, 1, 1) / 1000;
  const input = study(); input.series.interval = "1M"; input.sourceSeries!.interval = "1d";
  input.rows = Array.from({ length: 32 }, (_, i) => ({ time: start + i * 86400,
    closeTimeMs: (start + (i + 1) * 86400) * 1000, open: 10, high: 20 + i,
    low: 2, close: 15, volume: 1, is_closed: true }));
  const playback = new HistoryStudyPlayback(input, Date.UTC(2024, 1, 20, 12));
  assert.equal(playback.store.barCount, 1);
  assert.equal(playback.store.last()!.volume, 19);
  assert.equal(playback.store.last()!.high, 38);
  assert.equal(playback.store.last()!.is_closed, false);
  playback.seek(Date.UTC(2024, 2, 1));
  assert.equal(playback.store.last()!.volume, 29);
  assert.equal(playback.store.last()!.is_closed, true);
});

test("different source semantics and non-tiling intervals cannot become an apparent display study", () => {
  const input = study(); input.sourceSeries!.symbol = "ETHUSDT";
  assert.throws(() => new HistoryStudyPlayback(input, 300_000));
  input.sourceSeries!.symbol = "BTCUSDT"; input.sourceSeries!.interval = "3m";
  assert.throws(() => new HistoryStudyPlayback(input, 300_000));
});
