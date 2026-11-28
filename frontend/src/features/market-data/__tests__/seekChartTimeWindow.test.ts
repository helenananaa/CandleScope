import assert from "node:assert/strict";
import test from "node:test";
import { CHART_TIME_SEEK_REPAIR_BUDGET_MS, seekChartTimeWindow } from "../seekChartTimeWindow.js";
import { planChartTimeSeek } from "../chartTimeNavigation.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import { epochSeconds, partialMock } from "../../../test/testHelpers.js";
import type { KlineApi } from "../klineContracts.js";

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
    feed: { beginEpoch: () => 0, getRange: () => new Promise((resolve) => { resolveOld = resolve; }) },
    commit: () => commits.push(1),
  });
  owner = 2;
  const latest = await seekChartTimeWindow({ ...input(),
    feed: { beginEpoch: () => 0, getRange: async () => response() }, commit: () => commits.push(2) });
  resolveOld(response());
  assert.equal(latest.status, "located");
  assert.equal((await old).status, "superseded");
  assert.deepEqual(commits, [2]);
});

test("date seek uses a bounded range, and rechecks a cache proof only once", async () => {
  const calls: Parameters<SeriesDataFeed["getRange"]>[1][] = [];
  const result = await seekChartTimeWindow({ ...input(), hasCachedRange: true,
    feed: { beginEpoch: () => 0, getRange: async (_series, options) => {
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
      feed: { beginEpoch: () => 0, getRange: async () => { if (!candidate) throw new Error("offline"); return candidate; } },
      commit: () => { committed = true; },
    });
    assert.equal(committed, false);
    assert.equal(result.status, candidate?.data?.length === 0 ? "empty" : "unavailable");
  }
});

// Responses observed from the RC backend for a cold window: the strict read
// answers `pending` until the backfill (or the pre-listing proof) settles.
const pending = (missing: number, times: number[] = []): FeedResult => ({ ...response(times), rows: [], data: [],
  complete: false, retryable: true, verified_contiguous: false, history_state: "pending",
  missing_ranges: [{ start_ms: 60_000, end_ms: 60_000 + (missing - 1) * 60_000, reason: "query_empty", missing_bars: missing }] });
const clock = () => {
  let time = 0;
  return { now: () => time, delay: async (ms: number) => { time += ms; },
    advance: (ms: number) => { time += ms; } };
};

test("a cold far window keeps waiting for the backend repair and then locates the target", async () => {
  const fake = clock();
  const calls: Parameters<SeriesDataFeed["getRange"]>[1][] = [];
  const commits: FeedResult[] = [];
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async (_series, options) => {
      calls.push(options); fake.advance(1_500);
      return calls.length < 3 ? pending(3) : response();
    } }, commit: (value) => commits.push(value as FeedResult),
  });
  assert.deepEqual(result, { status: "located", requestedTimeMs: 120_000, actualTimeMs: 120_000, exact: true });
  assert.equal(calls.length, 3);
  assert.equal(commits.length, 1);
  for (const call of calls) {
    assert.equal(call?.repair, "wait"); assert.equal(call?.strict, true); assert.equal(call?.cacheMode, "network-only");
    assert.ok((call?.waitMs ?? 0) > 0 && (call?.waitMs ?? 0) <= 5_000);
    assert.equal(call?.start, 60); assert.equal(call?.end, 180); assert.equal(call?.maxPages, 1);
  }
});

test("a window that starts before the listing locates the first listed bar once the backend proves the gap", async () => {
  const fake = clock();
  let calls = 0;
  const listed = { ...response([180]), excluded_ranges: [{ start_ms: 60_000, end_ms: 179_999, disposition: "terminal", reason: "source_exhausted" }] };
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; fake.advance(1_500); return calls < 20 ? pending(2, [180]) : listed; } },
    commit: () => {},
  });
  assert.deepEqual(result, { status: "located", requestedTimeMs: 120_000, actualTimeMs: 180_000, exact: false });
  assert.equal(calls, 20);
});

test("an exhausted window before the listing reports empty, not unavailable", async () => {
  const fake = clock();
  let calls = 0;
  const exhausted: FeedResult = { ...response([]), history_state: "exhausted", terminal_reason: "source_exhausted" };
  let committed = false;
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; fake.advance(1_500); return calls < 3 ? pending(3) : exhausted; } },
    commit: () => { committed = true; },
  });
  assert.equal(result.status, "empty");
  assert.equal(committed, false);
});

test("a repair that never settles gives up at the budget, and an endpoint that answers at once is not spun on", async () => {
  const fake = clock();
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay, budgetMs: 10_000,
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; return pending(3); } }, commit: () => assert.fail("must not commit"),
  });
  assert.equal(result.status, "unavailable");
  // Instant answers are paced by the retry floor: 10 s / 0.5 s, plus the read at the deadline.
  assert.ok(calls >= 20 && calls <= 21, String(calls));
  assert.equal(fake.now(), 10_000);
});

// RC 32 (Binance spot BTCUSDT 1m, 2017-08-17 02:00): the pre-listing proof
// queued behind a gap audit's monthly archive import, and the backend finished
// after 117 s. Every answer meanwhile said it had joined a repair of the window.
const repairing = (missing: number, times: number[] = []): FeedResult => ({ ...pending(missing, times), backfill_triggered: true });

test("a seek keeps waiting past the budget while the backend is still repairing the window", async () => {
  const fake = clock();
  let calls = 0;
  const listed = { ...response([180]), excluded_ranges: [{ start_ms: 60_000, end_ms: 179_999, disposition: "terminal", reason: "source_exhausted" }] };
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => {
      calls += 1; fake.advance(5_000);
      return fake.now() < 117_000 ? repairing(2, [180]) : listed;
    } },
    commit: () => {},
  });
  assert.deepEqual(result, { status: "located", requestedTimeMs: 120_000, actualTimeMs: 180_000, exact: false });
  assert.equal(fake.now(), 120_000);
  assert.equal(calls, 24);
});

test("past the budget, a seek stops once the backend no longer reports a repair of the window", async () => {
  const fake = clock();
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => {
      calls += 1; fake.advance(5_000);
      return fake.now() < 70_000 ? repairing(3) : pending(3);
    } },
    commit: () => assert.fail("must not commit"),
  });
  assert.equal(result.status, "unavailable");
  assert.equal(fake.now(), 70_000);
  assert.equal(calls, 14);
});

test("a repair that is never finished gives up at the repair budget", async () => {
  const fake = clock();
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; fake.advance(5_000); return repairing(3); } },
    commit: () => assert.fail("must not commit"),
  });
  assert.equal(result.status, "unavailable");
  assert.equal(fake.now(), CHART_TIME_SEEK_REPAIR_BUDGET_MS);
  assert.equal(calls, CHART_TIME_SEEK_REPAIR_BUDGET_MS / 5_000);
});

test("a terminal refusal is reported at once instead of being retried", async () => {
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(),
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; return { ...pending(3), retryable: false }; } }, commit: () => {},
  });
  assert.equal(result.status, "unavailable");
  assert.equal(calls, 1);
});

test("a newer jump supersedes a seek that is waiting for the backend", async () => {
  const controller = new AbortController();
  let calls = 0;
  const waiting = seekChartTimeWindow({ ...input(), signal: controller.signal,
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; return pending(3); } }, commit: () => assert.fail("must not commit"),
  });
  await new Promise((resolve) => setTimeout(resolve, 50));
  controller.abort();
  assert.equal((await waiting).status, "superseded");
  const settledCalls = calls;
  await new Promise((resolve) => setTimeout(resolve, 600));
  assert.equal(calls, settledCalls);
});

test("a read fenced by a stream gap is read again while the seek still owns the window", async () => {
  const fake = clock();
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => { calls += 1; fake.advance(1_500); return calls === 1 ? { ...response(), stale: true } : response(); } },
    commit: () => {},
  });
  assert.equal(result.status, "located");
  assert.equal(calls, 2);
  // A disabled data plane is stale and inactive: not a transient fence.
  let disabledCalls = 0;
  const disabled = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { beginEpoch: () => 0, getRange: async () => { disabledCalls += 1; return { ...pending(3), stale: true, active: false, retryable: false }; } },
    commit: () => assert.fail("must not commit"),
  });
  assert.equal(disabled.status, "unavailable");
  assert.equal(disabledCalls, 1);
});

test("a backfill readback planned against the previous window cannot land in the window a seek committed", async () => {
  // RC rerun: with the Aug-20 window shown, the Oct-1 seek began its epoch. A
  // storage change for the Aug window was announced while the seek waited, so
  // its readback carried the seek's epoch. It landed after the Oct-1 window
  // replaced Aug, and older rows are always admitted: both windows were shown,
  // and the later hole fill was read back across the whole span.
  const version = { protocol: 1, epoch: "server-a", generation: 1, sequence: 9, barrier: 9, observed_at_ms: 1, stable: true,
    series: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "1m", provider_id: "binance", venue: "binance",
      asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" } };
  const ready = { complete: true, retryable: false, history_state: "ready" as const, verified_contiguous: true,
    missing_ranges: [], has_tail_gap: false, truncated: false, all_rows_final: true };
  const bars = (times: number[]) => times.map((time) => ({ time: epochSeconds(time), open: 1, high: 1, low: 1, close: 1, volume: 1, is_closed: true }));
  const previousWindow = bars([60, 120, 180]);
  const target = planChartTimeSeek("1m", 10_000_000, 20_000_000, 3)!;
  let releaseReadback: (() => void) | null = null;
  const committed: number[][] = [];
  const feed = new SeriesDataFeed({
    api: partialMock<KlineApi>({
      fetchKlinesRange: async (_symbol, _interval, start, end, _market, _exchange, options) => {
        if (options?.storageRevisionFloor) {
          await new Promise<void>((resolve) => { releaseReadback = resolve; });
          return { ...ready, data: previousWindow, stream_version: version, storage_revision: 10 };
        }
        return { ...ready, data: bars([Number(start), (Number(start) + Number(end)) / 2, Number(end)]) };
      },
    }),
    getActiveSeries: () => series,
    commitMergedChartData: (_symbol, _interval, rows) => { committed.push(rows.map((row) => Number(row.time))); },
  });
  feed.beginEpoch(series); // the runtime's seek starts its own epoch first
  assert.equal(feed.handleBackfillCompleted({
    type: "backfill_completed", symbol: series.symbol, interval: series.interval, exchange: series.exchange,
    market_type: series.marketType, stream_version: version,
    detail: { reason: "storage_history_changed", storage_revision: 10, range_start_ms: 60_000, range_end_ms: 180_000 },
  }, { activeSeries: series, getCacheRows: () => previousWindow, cooldownMs: 0 }), true);
  for (let i = 0; i < 100 && !releaseReadback; i += 1) await new Promise<void>((resolve) => setTimeout(resolve, 2));
  assert.ok(releaseReadback, "the readback is in flight while the seek runs");
  const replaced: number[][] = [];
  const result = await seekChartTimeWindow({ plan: target, series, feed, signal: new AbortController().signal,
    hasCachedRange: false, ownsRequest: () => true,
    commit: (value) => { replaced.push((value.data ?? []).map((row) => Number(row.time))); } });
  assert.equal(result.status, "located");
  assert.deepEqual(replaced, [[9_900, 9_960, 10_020]]);
  releaseReadback!();
  for (let i = 0; i < 100 && feed.backfillReloadInFlight.size; i += 1) await new Promise<void>((resolve) => setTimeout(resolve, 2));
  assert.deepEqual(committed, [], "the previous window's rows reached the new window");
});
