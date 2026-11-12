import assert from "node:assert/strict";
import test from "node:test";
import { readLatestWindow } from "../readLatestWindow.js";
import { SharedMarketCache } from "../manager/sharedMarketCache.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { AppliedKlineResult, KlineApi, KlineFetchResult } from "../klineContracts.js";
import type { EpochSeconds } from "../marketDataTypes.js";
import { partialMock } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const proof = (revision: number): KlineFetchResult => ({
  data: [60, 120].map(time => ({ time: time as EpochSeconds, open: 10, high: 20, low: 0, close: revision, volume: 1, is_closed: true })),
  all_rows_final: true, complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
  missing_ranges: [], has_tail_gap: false, storage_revision: revision,
  stream_version: { protocol: 1, epoch: "restore", generation: 1, sequence: revision, barrier: 0, stable: true,
    observed_at_ms: Date.now(), series: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "1m",
      provider_id: "binance", venue: "binance", asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" } },
});
const pending = (): AppliedKlineResult => ({ data: [], rows: [], complete: false, retryable: true, history_state: "pending", committed: false, stale: false, active: true });

test("one latest navigation survives a snapshot superseded by a concurrent cache read", async () => {
  const cache = new SharedMarketCache();
  cache.connect(series);
  let calls = 0, commits = 0;
  const feed = new SeriesDataFeed({ getActiveSeries: () => series, commitMergedChartData: () => { commits += 1; },
    api: partialMock<KlineApi>({ fetchKlinesHistory: async () => {
      const token = cache.beginRead(series);
      try {
        calls += 1;
        if (calls === 1) {
          const concurrent = cache.beginRead(series);
          try { cache.admitResponse(concurrent, proof(12)); } finally { concurrent.release(); }
          const rejected = cache.admitResponse(token, proof(11));
          assert.deepEqual(rejected.data, [], "a superseded snapshot must remain rejected");
          return rejected;
        }
        return cache.admitResponse(token, proof(13));
      } finally { token.release(); }
    } }),
  });
  const epoch = feed.beginEpoch(series);
  const result = await readLatestWindow({ read: () => feed.getBars(series, { countBack: 2, commit: "none" }),
    ownsRequest: () => feed.currentEpoch(series) === epoch, signal: new AbortController().signal });
  assert.ok(result, "the original UI action must obtain a fresh admitted snapshot");
  assert.deepEqual(result.data?.map(row => row.close), [13, 13]);
  assert.equal(calls, 2);
  assert.equal(feed.currentEpoch(series), epoch, "retry retains the same navigation owner");
  assert.equal(commits, 0, "only the caller may atomically replace its window");
});

test("pending latest reads stop at a fixed bound without admitting partial rows", async () => {
  let calls = 0;
  const result = await readLatestWindow({ read: async () => { calls += 1; return pending(); }, ownsRequest: () => true, signal: new AbortController().signal });
  assert.equal(result, null); assert.equal(calls, 3);
});

test("cancelling while a latest retry is waiting releases the action without another read", async () => {
  const controller = new AbortController(); let calls = 0;
  const result = readLatestWindow({ read: async () => { calls += 1; setTimeout(() => controller.abort(), 0); return pending(); },
    ownsRequest: () => true, signal: controller.signal });
  assert.equal(await result, null); assert.equal(calls, 1);
});

test("lost ownership and stale or inactive latest results never retry or publish", async () => {
  for (const mode of ["owner", "stale", "inactive"] as const) {
    let owns = true, calls = 0;
    const result = await readLatestWindow({ read: async () => { calls += 1; if (mode === "owner") owns = false;
      return { ...pending(), stale: mode === "stale", active: mode !== "inactive" }; },
      ownsRequest: () => owns, signal: new AbortController().signal });
    assert.equal(result, null); assert.equal(calls, 1);
  }
});

test("terminal unverified results and server cooldowns do not create a polling loop", async () => {
  for (const response of [{ ...pending(), retryable: false }, { ...pending(), retry_at_ms: Date.now() + 60_000 }]) {
    let calls = 0;
    assert.equal(await readLatestWindow({ read: async () => { calls += 1; return response; }, ownsRequest: () => true, signal: new AbortController().signal }), null);
    assert.equal(calls, 1);
  }
});
