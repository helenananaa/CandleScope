import assert from "node:assert/strict";
import test from "node:test";
import { canonicalizeIntervalValue, intervalWithAnchor, intervalTiles, intervalsSemanticallyEquivalent } from "../intervals.js";
import { createIntervalTimeline } from "../intervalTimeline.js";
import { sanitizeCustomIntervalRecords } from "../../features/chart-session/customIntervalStore.js";
import { klineDependencyKey } from "../../features/cache-gc/cacheRegistry.js";
import { isSameSeries } from "../../features/market-data/rangeRuntime.js";

const anchor = Date.parse("2026-10-27T00:02:00Z");
const target = intervalWithAnchor("7m", anchor);

test("event grid extends before and after anchor and canonicalizes aliases", () => {
  const timeline = createIntervalTimeline(target)!;
  for (const offset of [-100, -2, -1, 0, 1, 2, 100]) {
    const start = anchor / 1000 + offset * 420;
    assert.equal(timeline.floor(start + 419), start);
    assert.equal(timeline.next(start), start + 420);
    assert.equal(timeline.previous(start), start - 420);
  }
  assert.equal(intervalWithAnchor("420s", anchor + 420000), target);
  assert.equal(intervalWithAnchor("7m", anchor - 420000), target);
  assert.equal(canonicalizeIntervalValue("1h~a1~0"), "1h");
  assert.equal(intervalsSemanticallyEquivalent(target, "7m"), false);
});

test("seconds, calendar anchors and unknown versions fail closed", () => {
  for (const value of ["7m~a1~30000", "7m~a1~120001", "7s~a1~60000", "1w~a1~60000", "1M~a1~60000", "7m~a2~60000"]) {
    assert.equal(canonicalizeIntervalValue(value), "");
  }
  assert.equal(intervalWithAnchor("7m", anchor + 27000), "");
  const shifted = intervalWithAnchor("10m", anchor);
  assert.equal(intervalTiles("5m", shifted), false);
  assert.equal(intervalTiles("1m", shifted), true);
});

test("saved records keep the event and different phases keep separate cache identities", () => {
  const other = intervalWithAnchor("7m", anchor + 60000);
  const records = sanitizeCustomIntervalRecords([
    { value: target, anchorTimeMs: anchor },
    { value: `7m~a1~${anchor + 420000}`, anchorTimeMs: anchor + 420000 },
    { value: other, anchorTimeMs: anchor + 60000 },
  ]);
  assert.deepEqual(records.map(r => r.value), [target, other]);
  assert.equal(records[0]?.anchorTimeMs, anchor);
  assert.deepEqual(sanitizeCustomIntervalRecords(JSON.parse(JSON.stringify(records))), records);
  const base = { exchange: "okx", marketType: "spot", symbol: "BTC-USDT" };
  assert.notEqual(klineDependencyKey({ ...base, interval: target }), klineDependencyKey({ ...base, interval: other }));
  assert.equal(isSameSeries({ ...base, interval: target }, { ...base, interval: other }), false);
  const outsideDateRange = 8_700_000_000_000_000;
  const malformed = sanitizeCustomIntervalRecords([{ value: intervalWithAnchor("7m", outsideDateRange), anchorTimeMs: outsideDateRange }]);
  assert.equal(malformed[0]?.anchorTimeMs, undefined, "corrupt display metadata cannot crash date formatting");
});

test("replay display projection uses the same bidirectional grid", async () => {
  const { aggregateReplayBaseBars } = await import("../../features/replay/replayViewerProjection.js");
  const rows = Array.from({ length: 21 }, (_, i) => ({
    time: (anchor / 1000 + (i - 7) * 60) as import("../../features/market-data/marketDataTypes.js").KlineBar["time"],
    open: i, high: i + 2, low: i - 1, close: i + 1, volume: 1, is_closed: true,
  }));
  const bars = aggregateReplayBaseBars(rows, "1m", target);
  assert.deepEqual(bars.map(b => Number(b.time)), [anchor / 1000 - 420, anchor / 1000, anchor / 1000 + 420]);
  assert.deepEqual(bars.map(b => b.volume), [7, 7, 7]);
  assert.throws(() => aggregateReplayBaseBars(rows, "5m", intervalWithAnchor("10m", anchor)));
});
