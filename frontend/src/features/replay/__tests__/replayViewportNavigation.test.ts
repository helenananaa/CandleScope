import assert from "node:assert/strict";
import test from "node:test";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import { ReplayHistoryProvider } from "../replayHistoryProvider.js";
import { replayDisplayBarToKline } from "../replaySeriesProjection.js";
import { seekReplayViewportTime } from "../replayViewportNavigation.js";
import type { ReplayDisplayBar } from "../replayTypes.js";

const epoch = `sha256:${"a".repeat(64)}` as const;
const historyEpoch = `sha256:${"b".repeat(64)}` as const;
const identity = { exchange: "binance", market_type: "spot", symbol: "BTCUSDT",
  source_kind: "BAR" as const, base_interval: "1m", display_interval: "1m" };
function bar(time: number): ReplayDisplayBar {
  return { open_time_ms: time, close_time_ms: time + 59999, open: "100", high: "102", low: "99", close: "101", volume: "10",
    quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
    first_base_open_ms: time, last_base_open_ms: time, component_count: 1, expected_components: 1,
    is_closed: true, synthetic: false } as ReplayDisplayBar;
}
function fixture(change: (page: Record<string, unknown>) => void = () => {}, delay = Promise.resolve()) {
  const requests: URL[] = [];
  const provider = new ReplayHistoryProvider({ sessionId: "adapter-a", trackId: "track-a", identity,
    fetcher: async url => {
      const request = new URL(String(url), "http://localhost"); requests.push(request); await delay;
      const before = Number(request.searchParams.get("before_ms"));
      const page: Record<string, unknown> = { protocol: "replay.v3", schema_version: "replay.history.v3",
        run_id: "run-a", session_id: "adapter-a", track_id: "track-a", identity, data_epoch: epoch,
        history_epoch: historyEpoch, history_boundary_ms: 0,
        history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 20,
          visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: 60,
          effective_warmup_bars: 20, forward_cache_ms: 60000, interval_ms: 60000, policy_hash: epoch },
        revealed_boundary_ms: 3600000, bars: Array.from({ length: before / 60000 }, (_, i) => bar(i * 60000)),
        excluded_ranges: [], next_before_ms: 0, has_more: false };
      change(page); return Response.json(page);
    } });
  const store = new SeriesWindowStore({ maxBars: 1000 });
  store.replace([replayDisplayBarToKline(bar(3540000))]);
  return { provider, store, requests, requestedTimeMs: 600000, runId: "run-a", dataEpoch: epoch,
    revealedBoundaryMs: 3600000, current: () => true };
}

test("replay date navigation loads one bounded revealed page without changing its clock or another chart", async () => {
  const input = fixture();
  const other = fixture();
  const before = other.store.snapshot();
  const result = await seekReplayViewportTime(input);
  assert.deepEqual(result, { status: "located", requestedTimeMs: 600000, actualTimeMs: 600000, exact: true });
  assert.equal(input.requests.length, 1);
  const params = input.requests[0]!.searchParams;
  assert.equal(params.get("limit"), "500"); assert.equal(params.get("revealed_boundary_ms"), "3600000");
  assert.equal(input.revealedBoundaryMs, 3600000); assert.deepEqual(other.store.snapshot(), before);
  assert.equal(other.requests.length, 0);
  assert.ok(input.store.snapshot().every(row => Number(row.replayCloseTimeMs) <= input.revealedBoundaryMs));
});

test("loaded partial candles can be located, but a future date cannot issue a read", async () => {
  const input = fixture();
  const partial = { ...bar(3600000), is_closed: false, close_time_ms: 3659999 } as ReplayDisplayBar;
  input.store.applyRange([replayDisplayBarToKline(partial)]);
  assert.equal((await seekReplayViewportTime({ ...input, requestedTimeMs: 3600000 })).status, "located");
  assert.equal((await seekReplayViewportTime({ ...input, requestedTimeMs: 3600001 })).status, "invalid");
  assert.equal(input.requests.length, 0);
});

test("a declared source gap returns the earlier equidistant neighbour and its actual time", async () => {
  const input = fixture(page => {
    page.bars = (page.bars as ReplayDisplayBar[]).filter(row => row.open_time_ms !== 600000);
    page.excluded_ranges = [{ start_ms: 600000, end_ms: 659999, reason: "source_gap", source_reason: "missing" }];
  });
  assert.deepEqual(await seekReplayViewportTime(input), {
    status: "located", requestedTimeMs: 600000, actualTimeMs: 540000, exact: false,
  });
});

test("a late page after rewind, replaced input or a newer navigation never mutates the view", async () => {
  let release!: () => void;
  const input = fixture(() => {}, new Promise<void>(yes => { release = yes; }));
  let current = true; input.current = () => current;
  const before = input.store.snapshot(), pending = seekReplayViewportTime(input);
  current = false; release();
  assert.equal((await pending).status, "superseded"); assert.deepEqual(input.store.snapshot(), before);
});

test("a concurrently refreshed projection cannot be overwritten by an older date page", async () => {
  let release!: () => void;
  const input = fixture(() => {}, new Promise<void>(yes => { release = yes; }));
  const pending = seekReplayViewportTime(input);
  input.store.replace([replayDisplayBarToKline(bar(3480000))]); const fresh = input.store.snapshot(); release();
  assert.equal((await pending).status, "superseded"); assert.deepEqual(input.store.snapshot(), fresh);
});

test("wrong-run and future-closed replies fail before any display mutation", async () => {
  for (const [change, expected] of [
    [(page: Record<string, unknown>) => { page.run_id = "other-run"; }, /Replay viewport input changed/],
    [(page: Record<string, unknown>) => { page.bars = (page.bars as ReplayDisplayBar[]).map((row, index) =>
      index === 59 ? { ...row, close_time_ms: 3659999 } : row); }, /exceeds the revealed boundary/],
  ] as const) {
    const input = fixture(change), before = input.store.snapshot();
    await assert.rejects(seekReplayViewportTime(input), expected); assert.deepEqual(input.store.snapshot(), before);
  }
});
