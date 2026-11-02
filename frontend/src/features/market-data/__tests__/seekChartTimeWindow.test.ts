import assert from "node:assert/strict";
import test from "node:test";
import { seekChartTimeWindow } from "../seekChartTimeWindow.js";
import { planChartTimeSeek } from "../chartTimeNavigation.js";
import type { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const plan = planChartTimeSeek("1m", 120_000, 600_000, 3)!;
type FeedResult = Awaited<ReturnType<SeriesDataFeed["getRange"]>>;
const response = (times = [60, 120, 180]): FeedResult => {
  const data = times.map((time) => ({ time: epochSeconds(time), open: 1, high: 1, low: 1, close: 1, volume: 1, is_closed: true }));
  return { rows: data, data, complete: true, retryable: false, truncated: false, verified_contiguous: true,
    missing_ranges: [], has_tail_gap: false, all_rows_final: true, history_state: "ready" };
};
const input = () => ({ plan, series, signal: new AbortController().signal, hasCachedRange: false, ownsRequest: () => true });

test("a superseded request cannot commit even when the transport ignores abort", async () => {
  let resolveOld!: (value: FeedResult) => void;
  let owner = 1;
  const commits: number[] = [];
  const old = seekChartTimeWindow({ ...input(), ownsRequest: () => owner === 1,
    feed: { getRange: () => new Promise((resolve) => { resolveOld = resolve; }) },
    commit: () => commits.push(1),
  });
  owner = 2;
  const latest = await seekChartTimeWindow({ ...input(),
    feed: { getRange: async () => response() }, commit: () => commits.push(2) });
  resolveOld(response());
  assert.equal(latest.status, "located");
  assert.equal((await old).status, "superseded");
  assert.deepEqual(commits, [2]);
});

test("date seek uses a bounded range, and rechecks a cache proof only once", async () => {
  const calls: Parameters<SeriesDataFeed["getRange"]>[1][] = [];
  const result = await seekChartTimeWindow({ ...input(), hasCachedRange: true,
    feed: { getRange: async (_series, options) => {
      calls.push(options);
      return calls.length === 1 ? { ...response(), complete: false } : response([60, 180]);
    } }, commit: () => {},
  });
  assert.deepEqual(result, { status: "located", requestedTimeMs: 120_000, actualTimeMs: 60_000, exact: false });
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(call?.start, 60); assert.equal(call?.end, 180);
    assert.equal(call?.commit, "none"); assert.equal(call?.maxPages, 1);
  }
  assert.equal(calls[0]?.cacheMode, "prefer-cache");
  assert.equal(calls[1]?.cacheMode, "network-only");
});

test("failed, incomplete, empty and out-of-bounds windows retain the existing view", async () => {
  for (const candidate of [null, { ...response(), truncated: true }, response([]), response([0, 60])]) {
    let committed = false;
    const result = await seekChartTimeWindow({ ...input(),
      feed: { getRange: async () => { if (!candidate) throw new Error("offline"); return candidate; } },
      commit: () => { committed = true; },
    });
    assert.equal(committed, false);
    assert.equal(result.status, candidate?.data?.length === 0 ? "empty" : "unavailable");
  }
});
