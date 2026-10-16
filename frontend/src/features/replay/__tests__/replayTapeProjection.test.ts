import assert from "node:assert/strict";
import test from "node:test";
import { parseReplayTapeProjection, loadReplayTapeProjection } from "../replayTapeProjection.js";
import { ReplayV2ApiClient } from "../replayV2Api.js";

const epoch = `sha256:${"a".repeat(64)}`;
const ready = { protocol: "replay.v3", schema_version: "replay.tape-projection.v1", session_id: "session", track_id: "track-1",
  run_id: "run", identity: { exchange: "fixture", market_type: "spot", symbol: "BTCUSDT", source_kind: "AGG_TRADE", base_interval: "1m", display_interval: "90m" },
  history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2, visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null },
    visible_history_rows: 2, effective_warmup_bars: 2, forward_cache_ms: 60000, interval_ms: 60000, policy_hash: epoch },
  history_scope: "FROZEN_WARMUP_AND_TAPE",
  history_epoch: epoch, context_prepared_before_ms: 0, context_target_before_ms: 0, incomplete_context_buckets: [],
  display_interval: "90m", data_epoch: epoch, revealed_boundary_ms: 120_000, source_sequence: 8, prepared_sequence: 8,
  target_sequence: 8, before_ms: null, history_boundary_ms: 0, next_before_ms: 0, has_more: false,
  status: "ready", bars: [] };
const pending = { ...ready, status: "preparing", prepared_sequence: 3, next_before_ms: null, has_more: null };
const request = { trackId: "track-1", displayInterval: "90m", dataEpoch: epoch, revealedBoundaryMs: 120_000, sourceSequence: 8, limit: 5 };

test("tape parser rejects hidden fields, impossible progress and future bars", () => {
  assert.equal(parseReplayTapeProjection(ready).status, "ready");
  assert.equal(parseReplayTapeProjection(pending).prepared_sequence, 3);
  for (const value of [{ ...ready, actual_time_ms: 123 }, { ...ready, prepared_sequence: 7 },
    { ...pending, prepared_sequence: 8 }, { ...ready, source_sequence: Number.MAX_SAFE_INTEGER + 1 },
    { ...ready, bars: [{ open_time_ms: 120_001, close_time_ms: 180_000, open: "1", high: "1", low: "1", close: "1", volume: "1",
      quote_volume: null, trades: 1, taker_buy_base: null, taker_buy_quote: null, first_base_open_ms: 120_001,
      last_base_open_ms: 120_001, component_count: 1, expected_components: 1, is_closed: false, synthetic: false }] }]) {
    assert.throws(() => parseReplayTapeProjection(value));
  }
});

test("tape requests bind the source sequence even when the public timestamp matches", async () => {
  for (const changed of [{ source_sequence: 7, prepared_sequence: 7, target_sequence: 7 }, { session_id: "other" }, { data_epoch: `sha256:${"b".repeat(64)}` }]) {
    const api = new ReplayV2ApiClient({ basePath: "http://fixture.test/api/v1/replay", fetcher: async input => {
      const url = new URL(String(input));
      assert.equal(url.searchParams.get("source_sequence"), "8");
      assert.equal(url.searchParams.get("display_interval"), "90m");
      return Response.json({ ...ready, ...changed });
    } });
    await assert.rejects(api.tapeProjectionBySession("session", request), { code: "REPLAY_V2_PROTOCOL_ERROR" });
  }
});

test("historical pages bind their cursor and stop at a smaller consumed sequence", async () => {
  const older = { ...ready, display_interval: "1m", identity: { ...ready.identity, display_interval: "1m" }, before_ms: 120_000, source_sequence: 8,
    target_sequence: 4, prepared_sequence: 4, next_before_ms: 60_000, has_more: true };
  assert.equal(parseReplayTapeProjection(older).target_sequence, 4);
  for (const changed of [{ next_before_ms: 120_000 }, { has_more: false }, { target_sequence: 9 },
    { before_ms: 120_002 }, { next_before_ms: null }, { target_sequence: 3 }]) {
    assert.throws(() => parseReplayTapeProjection({ ...older, ...changed }));
  }
  let actual = older;
  const api = new ReplayV2ApiClient({ basePath: "http://fixture.test/api/v1/replay", fetcher: async input => {
    assert.equal(new URL(String(input)).searchParams.get("before_ms"), "120000");
    return Response.json(actual);
  } });
  const historical = { ...request, displayInterval: "1m", beforeMs: 120_000 };
  assert.equal((await api.tapeProjectionBySession("session", historical)).prepared_sequence, 4);
  actual = { ...older, before_ms: 60_000, next_before_ms: 0, has_more: false };
  await assert.rejects(api.tapeProjectionBySession("session", historical), { code: "REPLAY_V2_PROTOCOL_ERROR" });
});

test("bounded tape preparation advances, settles, and rejects a stalled continuation", async () => {
  let calls = 0;
  const progress: number[] = [];
  const result = await loadReplayTapeProjection(async () => parseReplayTapeProjection(++calls === 1 ? pending : ready),
    new AbortController().signal, value => { progress.push(value); });
  assert.equal(result.status, "ready"); assert.deepEqual(progress, [3]); assert.equal(calls, 2);
  await assert.rejects(loadReplayTapeProjection(async () => parseReplayTapeProjection(pending), new AbortController().signal), /did not progress/);
  calls = 0;
  await assert.rejects(loadReplayTapeProjection(async () => parseReplayTapeProjection(++calls === 1 ? pending
    : { ...ready, target_sequence: 7, prepared_sequence: 7 }), new AbortController().signal), /source changed/);
});

test("leaving a review cancels preparation without another request", async () => {
  const abort = new AbortController(); let calls = 0;
  await assert.rejects(loadReplayTapeProjection(async () => { calls++; return parseReplayTapeProjection(pending); },
    abort.signal, () => abort.abort()), { name: "AbortError" });
  assert.equal(calls, 1);
});

test("context and trade progress are distinct and preserve the pinned generation", async () => {
  const context = { ...pending, history_scope: "CONTEXT_AND_FROZEN_TAPE", prepared_sequence: 0,
    context_prepared_before_ms: 60_000, context_target_before_ms: 120_000 };
  const trading = { ...context, context_prepared_before_ms: 120_000, prepared_sequence: 3 };
  const done = { ...ready, history_scope: "CONTEXT_AND_FROZEN_TAPE",
    context_prepared_before_ms: 120_000, context_target_before_ms: 120_000 };
  const responses = [context, trading, done];
  const progress: [number, number, string][] = [];
  await loadReplayTapeProjection(async () => parseReplayTapeProjection(responses.shift()), new AbortController().signal,
    (at, target, phase) => { progress.push([at, target, phase]); });
  assert.deepEqual(progress, [[60_000, 120_000, "context"], [3, 8, "trades"]]);
  for (const values of [[trading, context], [context, { ...done, history_epoch: `sha256:${"b".repeat(64)}` }]]) {
    await assert.rejects(loadReplayTapeProjection(async () => parseReplayTapeProjection(values.shift()),
      new AbortController().signal), /earlier phase|source changed/);
  }
  assert.throws(() => parseReplayTapeProjection({ ...done, incomplete_context_buckets: [60_000, 0] }));
  assert.throws(() => parseReplayTapeProjection({ ...done, context_prepared_before_ms: 120_001 }));
});

test("history download retries are bounded and cancellable without hiding source failures", async () => {
  const downloading = Object.assign(new Error("downloading"), { code: "HISTORY_DOWNLOAD_PENDING" });
  let calls = 0, pendingNotices = 0;
  const options = { pendingRetryDelaysMs: [0, 0], pending: () => { pendingNotices++; } };
  const result = await loadReplayTapeProjection(async () => {
    if (++calls < 3) throw downloading;
    return parseReplayTapeProjection(ready);
  }, new AbortController().signal, undefined, options);
  assert.equal(result.status, "ready"); assert.equal(calls, 3); assert.equal(pendingNotices, 2);
  calls = 0;
  await assert.rejects(loadReplayTapeProjection(async () => { calls++; throw downloading; },
    new AbortController().signal, undefined, options), downloading);
  assert.equal(calls, 3);
  calls = 0;
  const missing = Object.assign(new Error("missing source"), { code: "HISTORY_SOURCE_INCOMPLETE" });
  await assert.rejects(loadReplayTapeProjection(async () => { calls++; throw missing; },
    new AbortController().signal, undefined, options), missing);
  assert.equal(calls, 1);
  const abort = new AbortController(); calls = 0;
  await assert.rejects(loadReplayTapeProjection(async () => { calls++; throw downloading; },
    abort.signal, undefined, { pending: () => abort.abort() }), { name: "AbortError" });
  assert.equal(calls, 1);
});

test("temporary archive reads retry the same tape window while corruption fails immediately", async () => {
  for (const retryable of [true, false]) {
    let calls = 0;
    const error = Object.assign(new Error("source unavailable"), { code: "HISTORY_SOURCE_UNAVAILABLE", details: { retryable } });
    const load = async () => { if (++calls < 3) throw error; return parseReplayTapeProjection(ready); };
    const request = loadReplayTapeProjection(load, new AbortController().signal, undefined, { pendingRetryDelaysMs: [0, 0, 0, 0] });
    if (retryable) assert.equal((await request).status, "ready");
    else await assert.rejects(request, error);
    assert.equal(calls, retryable ? 3 : 1);
    calls = 0;
    await assert.rejects(loadReplayTapeProjection(async () => { calls++; throw error; },
      new AbortController().signal, undefined, { pendingRetryDelaysMs: [0, 0, 0, 0] }), error);
    assert.equal(calls, retryable ? 3 : 1);
  }
});
