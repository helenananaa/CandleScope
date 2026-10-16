import assert from "node:assert/strict";
import test from "node:test";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import { CANONICAL_HISTORY_REFRESH } from "../replayCanonicalIndicators.js";
import { ReplayHistoryProvider, type ReplayHistoryIdentity } from "../replayHistoryProvider.js";
import { ReplayReviewHistory, type ReplayReviewHistoryState } from "../replayReviewHistory.js";
import { REVIEW_INITIAL_BARS, REVIEW_PREFIX_MAX_BARS } from "../replayReviewPrefix.js";
import type { ReplayDisplayBar } from "../replayTypes.js";

const epoch = `sha256:${"a".repeat(64)}` as const;
const historyEpoch = `sha256:${"b".repeat(64)}` as const;
const laterEpoch = `sha256:${"c".repeat(64)}` as const;
const start = 1_800_000_000_000;
const identity: ReplayHistoryIdentity = { exchange: "fixture", market_type: "spot", symbol: "LTCUSDT",
  source_kind: "AGG_TRADE", base_interval: "1m", display_interval: "1m" };
function rows(count: number, width = 60_000): ReplayDisplayBar[] {
  return Array.from({ length: count }, (_, index) => ({ open_time_ms: start + index * width,
    close_time_ms: start + (index + 1) * width - 1, open: "100", high: "102", low: "99", close: "101", volume: "10",
    quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
    first_base_open_ms: start + index * width, last_base_open_ms: start + (index + 1) * width - 60_000,
    component_count: width / 60_000, expected_components: width / 60_000, is_closed: true, synthetic: false })) as ReplayDisplayBar[];
}
function fixture(count = 1200, selected = identity, width = 60_000) {
  const available = rows(count, width), boundary = available.at(-1)!.close_time_ms;
  const calls: URL[] = [], progress: ReplayReviewHistoryState[] = [];
  const target = new SeriesWindowStore({ maxBars: REVIEW_PREFIX_MAX_BARS });
  let fail = false;
  const fetcher: typeof fetch = async input => {
    const url = new URL(String(input), "http://fixture.test");
    calls.push(url);
    if (fail) { fail = false; return new Response(JSON.stringify({ error: { message: "temporary read failure" } }), { status: 503 }); }
    assert.equal(url.searchParams.get("display_interval"), selected.display_interval);
    const before = Number(url.searchParams.get("before_ms")), limit = Number(url.searchParams.get("limit"));
    const matched = available.filter(row => row.close_time_ms < before).slice(-limit);
    return new Response(JSON.stringify({ protocol: "replay.v3", schema_version: "replay.history.v3", run_id: "run",
      session_id: "adapter", track_id: "track-1", identity: selected, data_epoch: epoch,
      history_epoch: url.searchParams.get("history_epoch") ?? historyEpoch,
      history_boundary_ms: start, revealed_boundary_ms: boundary,
      history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
        visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: count,
        effective_warmup_bars: 2, forward_cache_ms: 86400000, interval_ms: 60000, policy_hash: epoch },
      bars: matched, excluded_ranges: [], next_before_ms: matched[0]?.open_time_ms ?? before,
      has_more: matched[0]!.open_time_ms > start }));
  };
  const provider = new ReplayHistoryProvider({ sessionId: "adapter", trackId: "track-1", identity: selected, fetcher });
  return { available, boundary, calls, progress, target, provider, failNext: () => { fail = true; } };
}
const noProjection = async (): Promise<never> => { throw new Error("BAR projection requested for tape/base review"); };

test("review opens one selected-period page without indicators and pages left without losing its event tail", async () => {
  const f = fixture();
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, value => f.progress.push(value), noProjection);
  await history.initialize("selected-event");
  assert.equal(f.calls.length, 1);
  assert.equal(f.target.barCount, REVIEW_INITIAL_BARS);
  const tail = f.target.last();
  const work = history.loadMoreLeft();
  assert.equal(history.loadMoreLeft(), work);
  await work;
  assert.equal(f.target.barCount, 1000);
  await history.loadMoreLeft();
  assert.equal(f.target.barCount, 1200);
  assert.equal(f.progress.at(-1)!.hasMore, false);
  await history.loadMoreLeft();
  assert.equal(f.calls.length, 3);
  assert.deepEqual(f.target.last(), tail);
  assert.equal(f.target.seriesKey, "selected-event");
  history.cancel();
});

test("review pagination errors preserve the displayed chart and retry the same cursor", async () => {
  const f = fixture();
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, value => f.progress.push(value), noProjection);
  await history.initialize("review");
  const before = f.target.snapshot();
  f.failNext(); await history.loadMoreLeft();
  assert.deepEqual(f.target.snapshot(), before);
  assert.equal(f.progress.at(-1)!.error, "temporary read failure");
  await history.loadMoreLeft();
  assert.equal(f.calls[1]!.href, f.calls[2]!.href);
  assert.equal(f.target.barCount, 1000);
  assert.equal(f.progress.at(-1)!.error, null);
  history.cancel();
});

test("review adopts a canonical cache epoch before subsequent left paging", async () => {
  const f = fixture();
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, () => {}, noProjection);
  await history.initialize("review");
  f.target.correctWindow(f.target.snapshot(), { source: CANONICAL_HISTORY_REFRESH, sessionId: "adapter",
    trackId: "track-1", dataEpoch: epoch, historyEpoch: laterEpoch });
  await history.loadMoreLeft();
  assert.equal(f.calls[1]!.searchParams.get("history_epoch"), laterEpoch);
  history.cancel();
});

test("review capacity stops requests while preserving the selected event", async () => {
  const f = fixture(REVIEW_PREFIX_MAX_BARS + 50);
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, value => f.progress.push(value), noProjection);
  await history.initialize("review");
  const tail = f.target.last();
  for (let i = 0; i < 42; i++) await history.loadMoreLeft();
  assert.equal(f.target.barCount, REVIEW_PREFIX_MAX_BARS);
  assert.equal(f.calls.length, REVIEW_PREFIX_MAX_BARS / REVIEW_INITIAL_BARS);
  assert.equal(f.progress.at(-1)!.bounded, true);
  assert.deepEqual(f.target.last(), tail);
  assert.equal(f.target.rightTruncated, false);
  history.cancel();
});

test("canonical origin extension reopens an exhausted review history", async () => {
  const f = fixture(3);
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, value => f.progress.push(value), noProjection);
  await history.initialize("review");
  assert.equal(f.progress.at(-1)!.hasMore, false);
  f.target.correctWindow(f.target.snapshot(), { source: CANONICAL_HISTORY_REFRESH, sessionId: "adapter",
    trackId: "track-1", dataEpoch: epoch, historyEpoch: laterEpoch, hasMore: true });
  assert.equal(f.progress.at(-1)!.hasMore, true);
  assert.equal(f.progress.at(-1)!.bounded, false);
  history.cancel();
});

test("selected coarse BAR rows keep their server phase and append the revealed server tail", async () => {
  const selected = { ...identity, source_kind: "BAR" as const, display_interval: "7m" };
  const f = fixture(3, selected, 420_000);
  const forming = { ...f.available.at(-1)!, close: "101.25", is_closed: false } as ReplayDisplayBar;
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, () => {}, async (_id, request) => {
    assert.equal(request.displayInterval, "7m");
    return { protocol: "replay.v3", schema_version: "replay.display-projection.v1", run_id: "run", session_id: "adapter",
      track_id: "track-1", identity: selected, data_epoch: epoch, projection_epoch: epoch,
      display_interval: "7m", revealed_boundary_ms: f.boundary, has_more: false, bars: [forming] };
  });
  await history.initialize("review-7m");
  assert.deepEqual(f.target.snapshot().map(row => Number(row.time) * 1000), f.available.map(row => row.open_time_ms));
  assert.equal(f.target.intervalSeconds, 420);
  assert.equal(f.target.last()!.close, 101.25);
  assert.equal(f.target.last()!.replayClosed, false);
  history.cancel();
});

test("a canceled review read cannot publish into its successor chart", async () => {
  const f = fixture();
  let finish!: (value: Response) => void;
  const provider = new ReplayHistoryProvider({ sessionId: "adapter", trackId: "track-1", identity,
    fetcher: async () => await new Promise<Response>(resolve => { finish = resolve; }) });
  const history = new ReplayReviewHistory(f.target, provider, epoch, f.boundary, () => {}, noProjection);
  const pending = history.initialize("old-event");
  history.cancel();
  f.target.replace([{ time: 1000, open: 5, high: 5, low: 5, close: 5, volume: 1 }]);
  const successor = f.target.snapshot();
  finish(new Response("{}"));
  await assert.rejects(pending, { name: "AbortError" });
  assert.deepEqual(f.target.snapshot(), successor);
});

test("coarse tape review cannot silently substitute a closed-only BAR window", async () => {
  const f = fixture(3, { ...identity, display_interval: "90m" }, 5_400_000);
  const history = new ReplayReviewHistory(f.target, f.provider, epoch, f.boundary, () => {}, noProjection);
  await assert.rejects(history.initialize("tape-review"), /sequence-bound tail/);
  assert.equal(f.calls.length, 0);
  assert.equal(f.target.barCount, 0);
  history.cancel();
});
