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
    feed: { getRange: async (_series, options) => {
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
    feed: { getRange: async () => { calls += 1; fake.advance(1_500); return calls < 20 ? pending(2, [180]) : listed; } },
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
    feed: { getRange: async () => { calls += 1; fake.advance(1_500); return calls < 3 ? pending(3) : exhausted; } },
    commit: () => { committed = true; },
  });
  assert.equal(result.status, "empty");
  assert.equal(committed, false);
});

test("a repair that never settles gives up at the budget, and an endpoint that answers at once is not spun on", async () => {
  const fake = clock();
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay, budgetMs: 10_000,
    feed: { getRange: async () => { calls += 1; return pending(3); } }, commit: () => assert.fail("must not commit"),
  });
  assert.equal(result.status, "unavailable");
  // Instant answers are paced by the retry floor: 10 s / 0.5 s, plus the read at the deadline.
  assert.ok(calls >= 20 && calls <= 21, String(calls));
  assert.equal(fake.now(), 10_000);
});

test("a terminal refusal is reported at once instead of being retried", async () => {
  let calls = 0;
  const result = await seekChartTimeWindow({ ...input(),
    feed: { getRange: async () => { calls += 1; return { ...pending(3), retryable: false }; } }, commit: () => {},
  });
  assert.equal(result.status, "unavailable");
  assert.equal(calls, 1);
});

test("a newer jump supersedes a seek that is waiting for the backend", async () => {
  const controller = new AbortController();
  let calls = 0;
  const waiting = seekChartTimeWindow({ ...input(), signal: controller.signal,
    feed: { getRange: async () => { calls += 1; return pending(3); } }, commit: () => assert.fail("must not commit"),
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
    feed: { getRange: async () => { calls += 1; fake.advance(1_500); return calls === 1 ? { ...response(), stale: true } : response(); } },
    commit: () => {},
  });
  assert.equal(result.status, "located");
  assert.equal(calls, 2);
  // A disabled data plane is stale and inactive: not a transient fence.
  let disabledCalls = 0;
  const disabled = await seekChartTimeWindow({ ...input(), now: fake.now, delay: fake.delay,
    feed: { getRange: async () => { disabledCalls += 1; return { ...pending(3), stale: true, active: false, retryable: false }; } },
    commit: () => assert.fail("must not commit"),
  });
  assert.equal(disabled.status, "unavailable");
  assert.equal(disabledCalls, 1);
});
