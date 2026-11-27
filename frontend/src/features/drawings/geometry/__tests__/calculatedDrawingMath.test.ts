import assert from "node:assert/strict";
import test from "node:test";

import {
  anchoredVwap,
  barsBetween,
  calculationBars,
  fibExtensionLevels,
  fixedRangeVolumeProfile,
  regressionChannel,
  MAX_VOLUME_PROFILE_ROWS,
  MIN_VOLUME_PROFILE_ROWS,
} from "../calculatedDrawingMath.js";

const HOUR = 3600;
const DAY = 24 * HOUR;
// Friday 2026-11-20 14:30 UTC (a US session), then Monday after the weekend.
const FRIDAY = Date.UTC(2026, 10, 20, 14, 30) / 1000;
const MONDAY = FRIDAY + 3 * DAY;

function bar(time: number, close: number, volume = 100, spread = 1) {
  return { time, open: close, high: close + spread, low: close - spread, close, volume };
}

/** Three Friday bars, a weekend closure with no rows, three Monday bars. */
function sessionsWithClosure(closes = [1, 2, 3, 4, 5, 6]) {
  return [
    bar(FRIDAY, closes[0]!), bar(FRIDAY + HOUR, closes[1]!), bar(FRIDAY + 2 * HOUR, closes[2]!),
    bar(MONDAY, closes[3]!), bar(MONDAY + HOUR, closes[4]!), bar(MONDAY + 2 * HOUR, closes[5]!),
  ];
}

test("calculation bars skip whitespace and out-of-order rows and count by position", () => {
  const bars = calculationBars([
    bar(10, 1),
    { time: 20 },
    bar(30, 2, Number.NaN),
    bar(30, 99),
    bar(25, 99),
    { time: "2026-11-20", open: 1, high: 2, low: 0, close: 1 },
    bar(40, 3, -5),
  ]);
  assert.deepEqual(bars.map((item) => [item.index, item.time, item.close, item.volume]), [
    [0, 10, 1, 100],
    [1, 30, 2, 0],
    [2, 40, 3, 0],
  ]);
});

test("a range anchored inside a market closure starts at the next session's first bar", () => {
  const bars = calculationBars(sessionsWithClosure());
  const saturday = FRIDAY + DAY;
  assert.deepEqual(barsBetween(bars, saturday, MONDAY + HOUR).map((item) => item.time), [MONDAY, MONDAY + HOUR]);
  assert.deepEqual(barsBetween(bars, MONDAY + HOUR, saturday).map((item) => item.time), [MONDAY, MONDAY + HOUR],
    "anchors work in either order");
  assert.deepEqual(barsBetween(bars, saturday, saturday + HOUR), [], "a range wholly inside the closure has no bars");
});

test("fib extension projects levels from the pullback by the first move", () => {
  const levels = fibExtensionLevels(100, 150, 120);
  assert.deepEqual(levels.map((level) => level.ratio), [0, 0.618, 1, 1.272, 1.618, 2, 2.618]);
  assert.equal(levels.find((level) => level.ratio === 0)?.price, 120);
  assert.equal(levels.find((level) => level.ratio === 1)?.price, 170);
  assert.ok(Math.abs(levels.find((level) => level.ratio === 1.618)!.price - 200.9) < 1e-9);
  const down = fibExtensionLevels(150, 100, 130);
  assert.equal(down.find((level) => level.ratio === 1)?.price, 80, "a falling move extends down");
  assert.deepEqual(fibExtensionLevels(Number.NaN, 1, 2), []);
});

test("anchored VWAP accumulates typical price by volume from the anchor bar onward", () => {
  const bars = calculationBars([
    { time: 1, high: 12, low: 8, close: 10, volume: 100 },
    { time: 2, high: 22, low: 18, close: 20, volume: 0 },
    { time: 3, high: 32, low: 28, close: 30, volume: 300 },
  ]);
  assert.deepEqual(anchoredVwap(bars, 1), [
    { time: 1, price: 10 },
    { time: 2, price: 10 },
    { time: 3, price: (10 * 100 + 30 * 300) / 400 },
  ]);
  assert.deepEqual(anchoredVwap(bars, 2), [{ time: 3, price: 30 }], "no value until volume trades");
  assert.deepEqual(anchoredVwap(bars, 4), [], "an anchor after the last bar has nothing to average");
});

test("anchored VWAP has one point per bar and no point inside a closure", () => {
  const bars = calculationBars(sessionsWithClosure());
  const vwap = anchoredVwap(bars, FRIDAY + HOUR);
  assert.deepEqual(vwap.map((point) => point.time), [FRIDAY + HOUR, FRIDAY + 2 * HOUR, MONDAY, MONDAY + HOUR, MONDAY + 2 * HOUR]);
  assert.ok(vwap.every((point) => point.time < FRIDAY + 3 * HOUR || point.time >= MONDAY));
});

test("calculations only see the bars they are given, so replay cannot use unrevealed bars", () => {
  const all = calculationBars(sessionsWithClosure([10, 10, 10, 10, 50, 90]));
  const revealed = all.slice(0, 4);
  const replayVwap = anchoredVwap(revealed, FRIDAY);
  assert.equal(replayVwap.at(-1)?.time, MONDAY, "the VWAP ends at the last revealed bar");
  assert.equal(replayVwap.at(-1)?.price, 10, "later closes do not leak into the revealed value");
  const replayProfile = fixedRangeVolumeProfile(revealed, FRIDAY, MONDAY + 2 * HOUR);
  assert.equal(replayProfile?.barCount, 4);
  assert.equal(replayProfile?.endTime, MONDAY);
  assert.equal(regressionChannel(revealed, FRIDAY, MONDAY + 2 * HOUR)?.endTime, MONDAY);
});

test("volume profile is an estimate built from bar volume with POC and a 70% value area", () => {
  const bars = calculationBars([
    { time: 1, high: 110, low: 100, close: 105, volume: 100 },
    { time: 2, high: 104, low: 102, close: 103, volume: 400 },
    { time: 3, high: 109, low: 101, close: 108, volume: 80 },
  ]);
  const profile = fixedRangeVolumeProfile(bars, 1, 3, 10);
  assert.ok(profile);
  assert.equal(profile.estimated, true);
  assert.equal(profile.barCount, 3);
  assert.equal(profile.rows.length, 10);
  assert.equal(profile.low, 100);
  assert.equal(profile.high, 110);
  assert.ok(Math.abs(profile.totalVolume - 580) < 1e-9, "every bar's volume is kept");
  const poc = profile.rows[profile.pocIndex]!;
  assert.ok(poc.low >= 102 && poc.high <= 104, "the heavy narrow bar sets the point of control");
  const valueArea = profile.rows.filter((row) => row.inValueArea).reduce((sum, row) => sum + row.volume, 0);
  assert.ok(valueArea >= profile.totalVolume * 0.7);
  assert.ok(profile.rows[profile.pocIndex]!.inValueArea);
});

test("volume profile ignores bars outside the range, clamps rows and needs traded bars", () => {
  const bars = calculationBars(sessionsWithClosure());
  const profile = fixedRangeVolumeProfile(bars, MONDAY, MONDAY + 2 * HOUR, 1);
  assert.equal(profile?.barCount, 3);
  assert.equal(profile?.rows.length, MIN_VOLUME_PROFILE_ROWS);
  assert.equal(fixedRangeVolumeProfile(bars, FRIDAY, MONDAY, 10_000)?.rows.length, MAX_VOLUME_PROFILE_ROWS);
  assert.equal(fixedRangeVolumeProfile(calculationBars([bar(1, 5, 0)]), 1, 1), null);
  const flat = fixedRangeVolumeProfile(calculationBars([bar(1, 5, 10, 0)]), 1, 1, 4);
  assert.ok(flat && flat.high > flat.low, "a flat range still has visible rows");
});

test("regression channel fits closes by bar position, so a closure does not bend the slope", () => {
  const bars = calculationBars(sessionsWithClosure());
  const channel = regressionChannel(bars, FRIDAY, MONDAY + 2 * HOUR);
  assert.ok(channel);
  assert.equal(channel.barCount, 6);
  assert.ok(Math.abs(channel.slope - 1) < 1e-9, "one price unit per bar across the weekend");
  assert.ok(Math.abs(channel.startPrice - 1) < 1e-9);
  assert.ok(Math.abs(channel.endPrice - 6) < 1e-9);
  assert.ok(channel.standardDeviation < 1e-9);
  assert.equal(channel.startTime, FRIDAY);
  assert.equal(channel.endTime, MONDAY + 2 * HOUR);
});

test("regression channel rails sit the chosen number of standard deviations away", () => {
  const bars = calculationBars([bar(1, 10), bar(2, 12), bar(3, 10), bar(4, 12)]);
  const channel = regressionChannel(bars, 1, 4, 2);
  assert.ok(channel);
  assert.ok(channel.standardDeviation > 0);
  assert.ok(Math.abs(channel.offset - 2 * channel.standardDeviation) < 1e-12);
  assert.ok(Math.abs(regressionChannel(bars, 4, 1, 3)!.offset - 3 * channel.standardDeviation) < 1e-12);
  assert.equal(regressionChannel(bars, 1, 1), null, "one bar cannot define a line");
});
