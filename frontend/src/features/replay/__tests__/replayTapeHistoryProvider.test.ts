import assert from "node:assert/strict";
import test from "node:test";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import { createReplayHistoryProvider, ReplayTapeHistoryProvider } from "../replayTapeHistoryProvider.js";
import { ReplayReviewHistory } from "../replayReviewHistory.js";
import type { ReplayHistoryIdentity } from "../replayHistoryProvider.js";
import type { ReplayReviewHistoryState } from "../replayReviewHistory.js";

const epoch = `sha256:${"a".repeat(64)}` as const, historyEpoch = `sha256:${"b".repeat(64)}` as const;
const start = 1_800_000_000_000;
function fixture(count = 1200, width = 60_000) {
  const identity: ReplayHistoryIdentity = { exchange: "fixture", market_type: "spot", symbol: "FIXTURE",
    source_kind: "AGG_TRADE", base_interval: "1m", display_interval: `${width / 60000}m` };
  const rows = Array.from({ length: count }, (_, index) => ({ open_time_ms: start + index * width,
    close_time_ms: start + (index + 1) * width - 1, open: "100", high: "102", low: "99", close: "101", volume: "10",
    quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
    first_base_open_ms: start + index * width, last_base_open_ms: start + (index + 1) * width - 60000,
    component_count: width / 60000, expected_components: width / 60000, is_closed: true, synthetic: false }));
  const last = rows.at(-1)!;
  last.is_closed = false; last.component_count = 1; last.last_base_open_ms = last.open_time_ms;
  const boundary = last.open_time_ms + 1000, calls: URL[] = [];
  const gaps = new Set<number>();
  let fail = false;
  const fetcher: typeof fetch = async input => {
    const url = new URL(String(input), "http://fixture.test"); calls.push(url);
    assert.ok(url.pathname.endsWith("/tape-projection"));
    if (fail) { fail = false; return Response.json({ protocol: "replay.v3", error: { code: "HISTORY_SOURCE_INCOMPLETE", message: "read failed", details: {} } }, { status: 503 }); }
    const before = url.searchParams.has("before_ms") ? Number(url.searchParams.get("before_ms")) : null;
    const selected = rows.filter(row => before === null || row.open_time_ms < before).slice(-Number(url.searchParams.get("limit")));
    const cursor = selected[0]?.open_time_ms ?? before ?? start;
    const sequence = Number(url.searchParams.get("source_sequence"));
    return Response.json({ protocol: "replay.v3", schema_version: "replay.tape-projection.v1", run_id: "run",
      session_id: "session", track_id: "track-1", identity, data_epoch: epoch, display_interval: identity.display_interval,
      history_scope: "CONTEXT_AND_FROZEN_TAPE", history_epoch: url.searchParams.get("history_epoch") ?? historyEpoch,
      history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
        visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: count,
        effective_warmup_bars: 2, forward_cache_ms: 60000, interval_ms: 60000, policy_hash: epoch },
      context_prepared_before_ms: 0, context_target_before_ms: 0,
      incomplete_context_buckets: selected.filter(row => gaps.has(row.open_time_ms)).map(row => row.open_time_ms),
      revealed_boundary_ms: boundary, source_sequence: sequence, target_sequence: sequence, prepared_sequence: sequence,
      before_ms: before, history_boundary_ms: start, next_before_ms: cursor, has_more: cursor > start,
      status: "ready", bars: selected });
  };
  return { identity, rows, boundary, calls, gaps, fetcher, failNext: () => { fail = true; },
    options: { sessionId: "session", trackId: "track-1", identity, sourceSequence: 87, fetcher } };
}

test("tape review opens 500 selected-period bars and pages without losing its forming tail", async () => {
  const f = fixture(), store = new SeriesWindowStore({ maxBars: 20000 });
  const provider = createReplayHistoryProvider(f.options), progress: ReplayReviewHistoryState[] = [];
  const review = new ReplayReviewHistory(store, provider, epoch, f.boundary, state => progress.push(state));
  await review.initialize("tape-review");
  assert.equal(store.barCount, 500); assert.equal(f.calls[0]!.searchParams.has("before_ms"), false);
  const tail = store.last(); assert.equal(tail?.replayClosed, false);
  f.failNext(); await review.loadMoreLeft();
  assert.equal(store.barCount, 500); assert.equal(progress.at(-1)?.error, "read failed");
  await review.loadMoreLeft(); await review.loadMoreLeft();
  assert.equal(store.barCount, 1200); assert.deepEqual(store.last(), tail);
  assert.equal(progress.at(-1)?.hasMore, false);
  const requests = f.calls.length; await review.loadMoreLeft(); assert.equal(f.calls.length, requests);
  assert.ok(f.calls.every(url => url.searchParams.get("source_sequence") === "87"));
  assert.equal(f.calls[2]!.searchParams.get("history_epoch"), historyEpoch);
  review.cancel();
});

test("closed tape history excludes partial context buckets without weakening the closed-page parser", async () => {
  const f = fixture(6, 120000), provider = new ReplayTapeHistoryProvider(f.options);
  for (const index of [0, 2]) { f.rows[index]!.is_closed = false; f.rows[index]!.component_count = 1; }
  f.gaps.add(f.rows[2]!.open_time_ms);
  const request = { beforeMs: f.rows[5]!.open_time_ms, dataEpoch: epoch, revealedBoundaryMs: f.boundary };
  const page = await provider.loadBefore(request);
  assert.deepEqual(page.bars.map(row => row.open_time_ms), [1, 3, 4].map(index => f.rows[index]!.open_time_ms));
  assert.equal(page.excluded_ranges.length, 2); assert.equal(page.has_more, false);
  f.rows[3]!.is_closed = false; f.rows[3]!.component_count = 1;
  await assert.rejects(provider.loadBefore(request), /not closed by its selected tape sequence/);
  f.rows[3]!.is_closed = true; f.rows[3]!.component_count = 2;
  f.rows[0]!.component_count = 2;
  await assert.rejects(provider.loadBefore(request), /not closed by its selected tape sequence/);
  assert.throws(() => createReplayHistoryProvider({ ...f.options, sourceSequence: undefined }), /selected source/);
});

test("source changes invalidate forming windows while already-closed history survives forward playback", async () => {
  for (const closed of [false, true]) {
    const f = fixture(6); let sequence = 87, finish!: () => void;
    const gate = new Promise<void>(resolve => { finish = resolve; });
    const provider = new ReplayTapeHistoryProvider({ ...f.options, sourceSequence: () => sequence,
      fetcher: async (...args) => { await gate; return f.fetcher(...args); } });
    const request = { dataEpoch: epoch, revealedBoundaryMs: f.boundary, beforeMs: f.rows[5]!.open_time_ms };
    const work = closed ? provider.loadBefore(request) : provider.loadWindow(request);
    sequence++; finish();
    if (closed) assert.equal((await work).bars.length, 5);
    else await assert.rejects(work, { name: "AbortError" });
    provider.cancel();
  }
});
