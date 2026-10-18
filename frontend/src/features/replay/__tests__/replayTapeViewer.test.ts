import assert from "node:assert/strict";
import test from "node:test";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import { replayDisplayBarToKline } from "../replaySeriesProjection.js";
import { ReplayTapeViewer, type ReplayTapeViewerAuthority, type ReplayTapeViewerObservation } from "../replayTapeViewer.js";
import type { ReplayHistoryIdentity } from "../replayHistoryProvider.js";

const epoch = `sha256:${"a".repeat(64)}` as const, historyEpoch = `sha256:${"b".repeat(64)}` as const;
const start = 1_800_000_000_000;
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate: () => boolean) {
  const limit = performance.now() + 2500;
  while (!predicate()) { if (performance.now() > limit) assert.fail("viewer did not settle"); await delay(2); }
}
function fixture(maxBars = 2000, retainedFuture = false) {
  const identity: ReplayHistoryIdentity = { exchange: "fixture", market_type: "spot", symbol: "TEST",
    source_kind: "AGG_TRADE", base_interval: "1m", display_interval: "1m" };
  const target = new SeriesWindowStore({ maxBars }), source = new SeriesWindowStore({ seriesKey: "tape-source" });
  const state = { authority: { generation: 1, sourceSequence: 7, virtualTimeMs: start + 599999 } as ReplayTapeViewerAuthority | null,
    historyEpoch, count: 10, gap: false, fail: false, block: false };
  const observations: (ReplayTapeViewerObservation | null)[] = [], errors: (Error | null)[] = [], requests: URL[] = [];
  const waiting: (() => void)[] = [];
  let cancelled = 0;
  const rows = (count: number, sequence: number) => Array.from({ length: count }, (_, i) => ({
    open_time_ms: start + i * 60000, close_time_ms: start + i * 60000 + 59999,
    open: "10", high: "12", low: "9", close: "11", volume: String(i === count - 1 ? sequence : 1),
    quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
    first_base_open_ms: start + i * 60000, last_base_open_ms: start + i * 60000,
    component_count: 1, expected_components: 1, is_closed: i !== count - 1, synthetic: false }));
  const fetcher: typeof fetch = async (input, options) => {
    const url = new URL(String(input), "http://fixture"); requests.push(url);
    if (state.block) await new Promise<void>((resolve, reject) => {
      const abort = () => { cancelled++; reject(new DOMException("cancelled", "AbortError")); };
      options?.signal?.addEventListener("abort", abort, { once: true });
      waiting.push(() => { options?.signal?.removeEventListener("abort", abort); resolve(); });
      if (options?.signal?.aborted) abort();
    });
    if (state.fail) return Response.json({ protocol: "replay.v3", error: { code: "HISTORY_SOURCE_INCOMPLETE", message: "read failed", details: {} } }, { status: 503 });
    const before = url.searchParams.has("before_ms") ? Number(url.searchParams.get("before_ms")) : null;
    const sequence = Number(url.searchParams.get("source_sequence"));
    const candidates = rows(state.count, sequence).filter(row => before === null || row.open_time_ms < before);
    const selected = candidates.slice(-Number(url.searchParams.get("limit")));
    const cursor = selected[0]?.open_time_ms ?? before ?? start;
    return Response.json({ protocol: "replay.v3", schema_version: "replay.tape-projection.v1", run_id: "run",
      session_id: "session", track_id: "track-1", identity, data_epoch: epoch, display_interval: "1m",
      history_scope: "CONTEXT_AND_FROZEN_TAPE", history_epoch: state.historyEpoch,
      history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
        visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: state.count,
        effective_warmup_bars: 2, forward_cache_ms: 60000, interval_ms: 60000, policy_hash: epoch },
      context_prepared_before_ms: 0, context_target_before_ms: 0, incomplete_context_buckets: [],
      revealed_boundary_ms: Number(url.searchParams.get("revealed_boundary_ms")), source_sequence: sequence,
      target_sequence: sequence, prepared_sequence: sequence, before_ms: before, history_boundary_ms: start,
      next_before_ms: cursor, has_more: cursor > start, status: "ready", bars: state.gap ? [] : selected });
  };
  if (retainedFuture) target.replace(rows(10, 999).map(replayDisplayBarToKline));
  const viewer = new ReplayTapeViewer({ sessionId: "session", trackId: "track-1", dataEpoch: epoch, identity, source, target,
    authority: () => state.authority, observation: value => observations.push(value), loading: () => undefined,
    error: error => errors.push(error), fetcher });
  return { viewer, target, state, observations, errors, requests, rows, waiting, cancelled: () => cancelled,
    advance(sequence: number) { state.authority = { generation: 1, sourceSequence: sequence,
      virtualTimeMs: start + state.count * 60000 - 1 }; viewer.update(); } };
}

test("a newly bound observer hides retained unverified rows until its selected prefix arrives", async () => {
  const f = fixture(2000, true); f.state.block = true;
  try {
    assert.equal(f.target.barCount, 0);
    f.viewer.update(); await until(() => f.waiting.length === 1);
    assert.equal(f.target.barCount, 0);
    f.waiting[0]!(); await until(() => f.observations.length === 1);
    assert.equal(f.target.last()?.volume, 7);
  } finally { f.viewer.dispose(); }
});

test("forward source updates coalesce behind a fixed prefix without cancelling preparation", async () => {
  const f = fixture(); f.state.block = true;
  try {
    f.viewer.update(); await until(() => f.waiting.length === 1);
    for (let sequence = 8; sequence <= 30; sequence++) f.advance(sequence);
    assert.equal(f.requests.length, 1); assert.equal(f.cancelled(), 0);
    f.state.block = false; f.waiting[0]!();
    await until(() => f.observations.at(-1)?.sourceSequence === 30);
    assert.deepEqual(f.observations.map(value => value?.sourceSequence), [7, 30]);
    assert.equal(f.target.last()?.volume, 30); assert.equal(f.requests.length, 2);
  } finally { f.viewer.dispose(); }
});

test("rewind and authority loss cancel a delayed prefix and never publish future rows", async () => {
  const f = fixture(); f.state.block = true;
  try {
    f.viewer.update(); await until(() => f.waiting.length === 1);
    f.advance(2); await until(() => f.waiting.length === 2);
    f.state.block = false; f.waiting.splice(0).forEach(release => release());
    await until(() => f.observations.at(-1)?.sourceSequence === 2);
    assert.deepEqual(f.observations.map(value => value?.sourceSequence ?? null), [null, 2]);
    assert.equal(f.cancelled(), 1);
    f.state.authority = null; f.viewer.update(); assert.equal(f.target.barCount, 0);
    assert.equal(f.observations.at(-1), null);
  } finally { f.viewer.dispose(); }
});

test("historical prepend survives forward ticks; a truncated history view waits for explicit restore", async () => {
  const f = fixture(700); f.state.count = 600; f.advance(7);
  try {
    await until(() => f.observations.length === 1);
    assert.equal(f.requests[0]!.searchParams.get("limit"), "128");
    assert.equal(f.target.barCount, 128);
    assert.equal(f.observations[0]!.hasMore, true);
    // Normal left paging supplies the history omitted by the bootstrap. Its
    // oldest row must survive the next display refresh without a seam gap.
    f.target.applyRange(f.rows(472, 7).map(replayDisplayBarToKline));
    f.advance(8); await until(() => f.observations.at(-1)?.sourceSequence === 8);
    assert.equal(f.target.barCount, 600); assert.equal(f.target.first()?.time, start / 1000);
    f.target.applyRange(f.rows(200, 1).map(row => replayDisplayBarToKline({ ...row,
      open_time_ms: row.open_time_ms - 12000000, close_time_ms: row.close_time_ms - 12000000 })));
    assert.equal(f.target.rightTruncated, true);
    const before = f.target.snapshot(), count = f.requests.length;
    f.advance(9); await delay(120);
    assert.deepEqual(f.target.snapshot(), before); assert.equal(f.requests.length, count);
    assert.equal(await f.viewer.restoreLatest(), true);
    assert.equal(f.requests.at(-1)!.searchParams.get("limit"), "500");
    assert.equal(f.target.rightTruncated, false); assert.equal(f.target.barCount, 500);
    assert.equal(f.target.last()?.volume, 9);
  } finally { f.viewer.dispose(); }
});

test("large forward jumps fill the page seam within retention and stop scanning empty gaps", async () => {
  for (const gap of [false, true]) {
    const f = fixture(1200);
    try {
      f.viewer.update(); await until(() => f.observations.length === 1);
      f.state.count = 1010; f.state.gap = gap; f.advance(8);
      await until(() => f.observations.at(-1)?.sourceSequence === 8);
      assert.equal(f.requests.length, 4);
      if (gap) assert.equal(f.target.barCount, 0);
      else { assert.equal(f.target.barCount, 1010); assert.equal(f.target.first()?.time, start / 1000); }
    } finally { f.viewer.dispose(); }
  }
});

test("source failure is visible without a per-tick retry storm; explicit retry and disposal settle", async () => {
  const f = fixture(); f.state.fail = true;
  try {
    f.viewer.update(); await until(() => f.errors.some(Boolean));
    for (let sequence = 8; sequence < 30; sequence++) f.advance(sequence);
    await delay(120); assert.equal(f.requests.length, 1); assert.match(f.errors.find(Boolean)!.message, /read failed/);
    f.state.fail = false; assert.equal(await f.viewer.restoreLatest(), true);
    assert.equal(f.target.last()?.volume, 29);
    f.state.block = true; const pending = f.viewer.restoreLatest();
    await until(() => f.waiting.length === 1); f.viewer.dispose();
    assert.equal(await pending, false); assert.equal(f.cancelled(), 1);
  } finally { f.viewer.dispose(); }
});

test("history epoch replacement drops old loaded rows instead of mixing generations", async () => {
  const f = fixture();
  try {
    f.viewer.update(); await until(() => f.observations.length === 1);
    f.state.historyEpoch = `sha256:${"c".repeat(64)}`;
    f.state.count = 3; f.state.authority = { generation: 1, sourceSequence: 8, virtualTimeMs: start + 599999 };
    f.viewer.update(); await until(() => f.observations.at(-1)?.sourceSequence === 8);
    assert.equal(f.target.barCount, 3); assert.equal(f.observations.at(-1)?.historyEpoch, f.state.historyEpoch);
  } finally { f.viewer.dispose(); }
});
