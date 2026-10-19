import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseIndicatorPayloadEnvelope } from "../../indicators/indicatorContracts.js";
import type { IndicatorComputeBatchJob, IndicatorOhlcvBar, IndicatorValuePoint } from "../../indicators/indicatorTypes.js";
import { SeriesWindowStore } from "../../market-data/window/seriesWindowStore.js";
import { createReplayBuiltinCompute } from "../replayBuiltinCompute.js";
import { CANONICAL_HISTORY_REFRESH, ReplayCanonicalIndicators, replayIndicatorCalculationKey, type ReplayCanonicalBinding, type ReplayIndicatorPreparation } from "../replayCanonicalIndicators.js";
import { ReplayHistoryProvider } from "../replayHistoryProvider.js";
import { replayDisplayBarToKline } from "../replaySeriesProjection.js";
import type { ReplayBuiltinSeed } from "../replayBuiltinCompute.js";
import type { ReplayDigest, ReplayDisplayBar } from "../replayTypes.js";

const dataEpoch = `sha256:${"a".repeat(64)}` as const;
const historyEpoch = `sha256:${"b".repeat(64)}` as const;
const laterEpoch = `sha256:${"c".repeat(64)}` as const;
const fixture = JSON.parse(readFileSync(new URL("./fixtures/builtin-parity.json", import.meta.url), "utf8")) as {
  bars: IndicatorOhlcvBar[];
  cases: { name: string; params: object; outputs: Record<string, IndicatorValuePoint[]>;
    canonical: { prefix_count: number; initial_count: number; result: { payload: unknown; math_seed: ReplayBuiltinSeed } }[] }[];
};
const reference = fixture.cases.find(value => value.name === "RSI" && Object.keys(value.params).length === 0)!;
const sourceRows = fixture.bars.map(row => ({ open_time_ms: row.time * 1000, close_time_ms: row.time * 1000 + 59999,
  open: String(row.open), high: String(row.high), low: String(row.low), close: String(row.close), volume: String(row.volume),
  quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
  first_base_open_ms: row.time * 1000, last_base_open_ms: row.time * 1000, component_count: 1, expected_components: 1,
  is_closed: true, synthetic: false })) as ReplayDisplayBar[];
const binding: ReplayCanonicalBinding = { sessionId: "adapter", trackId: "track-1", dataEpoch,
  revealedBoundaryMs: sourceRows.at(-1)!.close_time_ms,
  identity: { exchange: "fixture", market_type: "spot", symbol: "FIXTURE", source_kind: "BAR", base_interval: "1m", display_interval: "1m" } };
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function job(store: SeriesWindowStore, id = "rsi"): IndicatorComputeBatchJob {
  return { clientId: id, jobKey: `${id}-${store.version}`, request: { mode: "builtin", name: "RSI", params: {},
    exchange: "fixture", marketType: "spot", symbol: "FIXTURE", interval: "1m",
    ohlcv: store.snapshot().map(row => ({ time: Number(row.time), open: Number(row.open), high: Number(row.high), low: Number(row.low),
      close: Number(row.close), volume: Number(row.volume), is_closed: row.replayClosed !== false })) } };
}
function seed(epoch: ReplayDigest = historyEpoch) {
  return { ...binding, session_id: binding.sessionId, track_id: binding.trackId, data_epoch: dataEpoch,
    history_epoch: epoch, identity: binding.identity, origin_ms: sourceRows[0]!.open_time_ms };
}
function ready(result = reference.canonical.find(value => value.prefix_count === 47)!.result, epoch: ReplayDigest = historyEpoch) {
  return { ...result, protocol: "replay.v3", status: "ready", seed: seed(epoch) };
}
function page(rows: ReplayDisplayBar[], before: number, epoch: ReplayDigest = historyEpoch) {
  return { protocol: "replay.v3", schema_version: "replay.history.v3", run_id: "run", session_id: binding.sessionId,
    track_id: binding.trackId, identity: binding.identity, data_epoch: dataEpoch, history_epoch: epoch,
    history_boundary_ms: sourceRows[0]!.open_time_ms, revealed_boundary_ms: binding.revealedBoundaryMs,
    history_policy: { schema_version: "replay.data-policy.v1", indicator_warmup_bars: 2,
      visible_history_lookback: { mode: "ALL_AVAILABLE", duration_ms: null }, visible_history_rows: 128,
      effective_warmup_bars: 2, forward_cache_ms: 86400000, interval_ms: 60000, policy_hash: dataEpoch },
    bars: rows, excluded_ranges: [], next_before_ms: rows[0]?.open_time_ms ?? before, has_more: false };
}
function storeWith(start = 47, stop = 50) {
  const store = new SeriesWindowStore({ seriesKey: "window", intervalSeconds: 60 });
  store.replace(sourceRows.slice(start, stop).map(replayDisplayBarToKline));
  return store;
}
const noProjection = async (): Promise<never> => { throw new Error("unexpected projection"); };

test("script fallback carries its captured replay clock and discards superseded replies", async () => {
  const store = storeWith(), submitted = job(store);
  let current = { ...binding, sourceSequence: 7 };
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const published: unknown[] = [];
  const source = new ReplayCanonicalIndicators(store, () => current, () => {}, fetch, noProjection,
    async ({ jobs }) => {
      assert.deepEqual(jobs[0]?.request.replayContext, {
        sessionId: binding.sessionId, trackId: binding.trackId, dataEpoch,
        revealedBoundaryMs: binding.revealedBoundaryMs, sourceSequence: 7,
      });
      assert.equal(jobs[0]?.request.ohlcv, submitted.request.ohlcv);
      await gate;
      return { ok: true, results: [{ clientId: submitted.clientId, jobKey: submitted.jobKey,
        payload: parseIndicatorPayloadEnvelope({ ok: true }) }] };
    });
  const script = { ...submitted, request: { ...submitted.request, mode: "script", language: "pine", script: "plot(close)" } };
  const work = source.compute({ jobs: [script], onResults: results => { published.push(results); } });
  current = { ...current, sourceSequence: 8 }; release();
  await assert.rejects(work, { name: "AbortError" });
  assert.deepEqual(published, []);
  assert.equal(script.request.replayContext, undefined);
});

test("metadata hydration and equal-price tape advances supersede old compute ownership", () => {
  const key = replayIndicatorCalculationKey("same-ohlcv", 10, 30, 1000);
  assert.equal(key, replayIndicatorCalculationKey("same-ohlcv", 10, 30, 1000));
  assert.notEqual(key, replayIndicatorCalculationKey("same-ohlcv", 11, 30, 1000));
  assert.notEqual(key, replayIndicatorCalculationKey("same-ohlcv", 10, 31, 1000));
  assert.notEqual(key, replayIndicatorCalculationKey("same-ohlcv", 10, 30, 1001));
});

test("a captured tape sample keeps its own metadata after the display advances", async () => {
  const store = storeWith(), submitted = job(store), sourceBars = [...store.snapshot()];
  const current: ReplayCanonicalBinding = { ...binding, sourceSequence: 7, historyEpoch, sourceBars,
    identity: { ...binding.identity, source_kind: "AGG_TRADE" } };
  store.applyTick({ ...store.last()!, volume: 999 });
  let calls = 0;
  const source = new ReplayCanonicalIndicators(store, () => current, () => {}, async (_url, options) => {
    calls++;
    const body = JSON.parse(String(options?.body)) as { source_sequence: number; bars: ReplayDisplayBar[] };
    assert.equal(body.source_sequence, 7); assert.equal(body.bars.at(-1)?.volume, "50");
    assert.equal(body.bars.at(-1)?.last_base_open_ms, sourceRows[49]!.last_base_open_ms);
    return reply({ ...ready(), seed: { ...seed(), identity: current.identity } });
  }, noProjection);
  assert.equal((await source.compute({ jobs: [submitted] })).ok, true);
  assert.equal(calls, 1); assert.equal(store.last()?.volume, 999);
  // A job from the newer chart cannot borrow the older observation's bounds.
  await assert.rejects(source.compute({ jobs: [job(store)] }), { name: "AbortError" });
  assert.equal(calls, 1);
});

test("changing the sampled history generation discards a delayed seed response", async () => {
  const store = storeWith();
  let current = { ...binding, historyEpoch, sourceBars: store.snapshot() };
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const source = new ReplayCanonicalIndicators(store, () => current, () => {}, async () => {
    await gate; return reply(ready());
  }, noProjection);
  const work = source.compute({ jobs: [job(store)] });
  current = { ...current, historyEpoch: laterEpoch }; release();
  await assert.rejects(work, { name: "AbortError" });
});

test("different chart windows resume the same Python RSI prefix and advance locally", async () => {
  for (const prefix of [47, 110]) {
    const example = reference.canonical.find(value => value.prefix_count === prefix)!;
    const store = storeWith(prefix, example.initial_count);
    let calls = 0;
    const source = new ReplayCanonicalIndicators(store, () => binding, () => {}, async (_url, options) => {
      calls++;
      const request = JSON.parse(String(options?.body)) as { bars: ReplayDisplayBar[]; data_epoch: string; history_epoch: string; revealed_boundary_ms: number };
      assert.equal(request.bars[0]!.open_time_ms, sourceRows[prefix]!.open_time_ms);
      assert.equal(request.data_epoch, dataEpoch);
      assert.equal(request.revealed_boundary_ms, binding.revealedBoundaryMs);
      return reply(ready(example.result));
    }, noProjection);
    const compute = createReplayBuiltinCompute(source.compute, { seedForPayload: source.seedForPayload, sourceKey: source.sourceKey });
    let output;
    for (let count = example.initial_count; count <= sourceRows.length; count++) {
      store.replace(sourceRows.slice(prefix, count).map(replayDisplayBarToKline));
      output = await compute({ jobs: [job(store)] });
    }
    assert.equal(calls, 1);
    assert.deepEqual(output!.results[0]!.payload.lines[0]!.data,
      reference.outputs.rsi!.filter(point => point.time >= fixture.bars[prefix]!.time));
  }
});

test("prefix preparation reports advancing progress and cancels without publishing", async () => {
  const store = storeWith();
  const progress: ReplayIndicatorPreparation[] = [];
  const abort = new AbortController();
  let calls = 0;
  const source = new ReplayCanonicalIndicators(store, () => binding, state => {
    progress.push(state);
    if (state.phase === "prefix") abort.abort();
  }, async () => {
    calls++;
    return reply({ protocol: "replay.v3", status: "preparing", seed: seed(),
      prepared_before_ms: sourceRows[20]!.open_time_ms, target_before_ms: sourceRows[47]!.open_time_ms });
  }, noProjection);
  await assert.rejects(source.compute({ jobs: [job(store)], signal: abort.signal }), { name: "AbortError" });
  assert.equal(calls, 1);
  assert.equal(progress.at(-1)!.active, 0);
  assert.ok(progress.some(value => value.prepared === sourceRows[20]!.open_time_ms));
  assert.equal(progress.find(value => value.phase === "prefix")!.fraction, 20 / 47);
  assert.equal(progress.at(-1)!.fraction, null);
});

test("a stalled prefix and another market's response become explicit errors", async () => {
  for (const failure of ["stalled", "identity"]) {
    const store = storeWith();
    let calls = 0;
    const source = new ReplayCanonicalIndicators(store, () => binding, () => {}, async () => {
      calls++;
      return reply(failure === "stalled" ? { protocol: "replay.v3", status: "preparing", seed: seed(),
        prepared_before_ms: sourceRows[20]!.open_time_ms, target_before_ms: sourceRows[47]!.open_time_ms }
        : { ...ready(), seed: { ...seed(), session_id: "another-market" } });
    }, noProjection);
    const result = await source.compute({ jobs: [job(store)] });
    assert.equal(result.ok, false);
    assert.match(result.results[0]!.payload.error!, failure === "stalled" ? /progress/ : /another source/);
    assert.equal(calls, failure === "stalled" ? 2 : 1);
    assert.deepEqual(result.results[0]!.payload.lines, []);
  }
});

test("epoch mismatch reloads actual prices once for concurrent indicators before resubmission", async () => {
  const store = storeWith();
  const versions: string[] = [], deltas: string[] = [];
  let posts = 0, gets = 0;
  const corrected = sourceRows.slice(47, 50).map(row => ({ ...row, close: String(Number(row.close) + 0.5) }) as ReplayDisplayBar);
  const source = new ReplayCanonicalIndicators(store, () => binding, () => {}, async (url, options) => {
    if (String(url).includes("/history?")) {
      gets++;
      // Let both indicators observe the epoch transition before this one load completes.
      await new Promise(resolve => setTimeout(resolve, 0));
      return reply(page(corrected, Number(new URL(String(url), "http://fixture.test").searchParams.get("before_ms"))));
    }
    const request = JSON.parse(String(options?.body)) as { bars: ReplayDisplayBar[]; data_epoch: string; history_epoch: string; revealed_boundary_ms: number };
    posts++;
    if (posts <= 2) return reply({ error: { code: "HISTORY_EPOCH_MISMATCH", message: "reload" } }, 409);
    versions.push(request.history_epoch);
    assert.equal(request.bars[0]!.close, corrected[0]!.close);
    return reply(ready());
  }, noProjection);
  const disconnect = source.connect();
  const unsubscribe = store.subscribe(delta => { if (typeof delta.source === "string") deltas.push(delta.source); });
  await assert.rejects(source.compute({ jobs: [job(store), job(store, "second-rsi")] }), { name: "AbortError" });
  assert.equal(gets, 1);
  assert.deepEqual(deltas, [CANONICAL_HISTORY_REFRESH]);
  assert.equal(store.seriesKey, "window");
  assert.equal(Number(store.first()!.close), Number(corrected[0]!.close));
  const response = await source.compute({ jobs: [job(store)] });
  assert.equal(response.ok, true);
  assert.deepEqual(versions, [historyEpoch]);
  disconnect(); unsubscribe();
});

test("review refreshes its own authoritative interval even before an epoch exists", async () => {
  const store = storeWith();
  let posts = 0, gets = 0;
  const source = new ReplayCanonicalIndicators(store, () => ({ ...binding, forceInitialRefresh: true }), () => {}, async (url) => {
    if (String(url).includes("/history?")) { gets++; return reply(page(sourceRows.slice(47, 50), sourceRows[50]!.open_time_ms)); }
    posts++; return reply(ready());
  }, noProjection);
  await assert.rejects(source.compute({ jobs: [job(store)] }), { name: "AbortError" });
  assert.equal(posts, 0);
  assert.equal(gets, 1);
  assert.equal((await source.compute({ jobs: [job(store)] })).ok, true);
  assert.equal(posts, 1);
});

test("changing replay event while a refresh is pending leaves its successor window untouched", async () => {
  const store = storeWith();
  let current = binding;
  let finish!: () => void;
  const waiting = new Promise<void>(resolve => { finish = resolve; });
  const source = new ReplayCanonicalIndicators(store, () => ({ ...current, forceInitialRefresh: true }), () => {}, async () => {
    await waiting;
    return reply(page(sourceRows.slice(47, 50), sourceRows[50]!.open_time_ms));
  }, noProjection);
  const promise = source.compute({ jobs: [job(store)] });
  current = { ...binding, revealedBoundaryMs: binding.revealedBoundaryMs - 60000 };
  store.replace(sourceRows.slice(70, 72).map(replayDisplayBarToKline));
  const expected = store.snapshot();
  finish();
  await assert.rejects(promise, { name: "AbortError" });
  assert.deepEqual(store.snapshot(), expected);
});

test("unrelated scripts start while the canonical prefix is preparing", async () => {
  const store = storeWith();
  let finish!: () => void;
  const waiting = new Promise<void>(resolve => { finish = resolve; });
  let scripts = 0;
  const source = new ReplayCanonicalIndicators(store, () => binding, () => {}, async () => {
    await waiting;
    return reply({ error: { code: "HISTORY_ORIGIN_UNKNOWN", message: "no confirmed origin" } }, 503);
  }, noProjection, async ({ jobs }) => {
    scripts++;
    return { ok: true, results: jobs.map(value => ({ clientId: value.clientId, jobKey: value.jobKey,
      payload: parseIndicatorPayloadEnvelope({ ok: true }) })) };
  });
  const promise = source.compute({ jobs: [job(store), { ...job(store, "script"), request: { ...job(store).request, mode: "script", script: "plot(close)" } }] });
  assert.equal(scripts, 1);
  finish();
  const result = await promise;
  assert.equal(result.results.find(value => value.clientId === "script")!.payload.ok, true);
  assert.match(result.results.find(value => value.clientId === "rsi")!.payload.error!, /confirmed origin/);
});

test("adopting a refreshed epoch cancels old history reads and sends the new epoch", async () => {
  let calls = 0;
  const provider = new ReplayHistoryProvider({ sessionId: binding.sessionId, trackId: binding.trackId, identity: binding.identity,
    fetcher: async (url, options) => {
      if (++calls === 1) return await new Promise<Response>((_resolve, reject) => options!.signal!.addEventListener("abort", () => reject(new DOMException("cancel", "AbortError")), { once: true }));
      assert.equal(new URL(String(url), "http://fixture.test").searchParams.get("history_epoch"), laterEpoch);
      return reply(page(sourceRows.slice(47, 50), sourceRows[50]!.open_time_ms, laterEpoch));
    } });
  const input = { beforeMs: sourceRows[50]!.open_time_ms, revealedBoundaryMs: binding.revealedBoundaryMs, dataEpoch };
  const first = provider.loadBefore(input);
  provider.adoptEpoch(laterEpoch);
  await assert.rejects(first, { name: "AbortError" });
  assert.equal((await provider.loadBefore(input)).history_epoch, laterEpoch);
  provider.cancel();
});

test("a refresh rejects undeclared missing boundary rows and keeps the visible chart", async () => {
  for (const omitted of ["left", "right", "all"]) {
    const store = storeWith(), before = store.snapshot();
    const available = omitted === "all" ? [] : sourceRows.slice(omitted === "left" ? 48 : 47, omitted === "right" ? 49 : 50);
    const source = new ReplayCanonicalIndicators(store, () => ({ ...binding, forceInitialRefresh: true }), () => {},
      async () => reply(page(available, sourceRows[50]!.open_time_ms)), noProjection);
    const result = await source.compute({ jobs: [job(store)] });
    assert.match(result.results[0]!.payload.error!, /undeclared chart range/);
    assert.deepEqual(store.snapshot(), before);
  }
});

test("declared missing historical bars are removed while the retained chart stays in place", async () => {
  const store = storeWith();
  const source = new ReplayCanonicalIndicators(store, () => ({ ...binding, forceInitialRefresh: true }), () => {}, async () => reply({
    ...page(sourceRows.slice(48, 50), sourceRows[50]!.open_time_ms),
    excluded_ranges: [{ start_ms: sourceRows[47]!.open_time_ms, end_ms: sourceRows[47]!.close_time_ms,
      reason: "source_gap", source_reason: "provider_gap" }],
  }), noProjection);
  await assert.rejects(source.compute({ jobs: [job(store)] }), { name: "AbortError" });
  assert.equal(store.first()!.time, sourceRows[48]!.open_time_ms / 1000);
  assert.equal(store.seriesKey, "window");
});

test("missing forming projection cannot silently remove the chart tail", async () => {
  const store = storeWith();
  store.applyTick({ ...store.last()!, replayClosed: false });
  const before = store.snapshot();
  const coarseBinding = { ...binding, identity: { ...binding.identity, display_interval: "5m" }, forceInitialRefresh: true };
  const source = new ReplayCanonicalIndicators(store, () => coarseBinding, () => {},
    async () => reply(page(sourceRows.slice(47, 49), sourceRows[49]!.open_time_ms)), async () => ({
      protocol: "replay.v3", schema_version: "replay.display-projection.v1", run_id: "run", identity: binding.identity,
      projection_epoch: dataEpoch, has_more: false,
      session_id: binding.sessionId, track_id: binding.trackId, data_epoch: dataEpoch, display_interval: "5m",
      revealed_boundary_ms: binding.revealedBoundaryMs, bars: [],
    }));
  const request = job(store);
  const result = await source.compute({ jobs: [{ ...request, request: { ...request.request, interval: "5m" } }] });
  assert.match(result.results[0]!.payload.error!, /forming chart tail/);
  assert.deepEqual(store.snapshot(), before);
});

test("epoch reload preserves the pinned base and tape forming tail without the BAR-only endpoint", async () => {
  for (const [sourceKind, minutes] of [["BAR", 1], ["AGG_TRADE", 1], ["AGG_TRADE", 90]] as const) {
    const store = storeWith();
    const start = sourceRows[47]!.open_time_ms;
    const window = sourceRows.slice(47, 50).map((row, index) => ({ ...row,
      open_time_ms: start + index * minutes * 60_000, close_time_ms: start + (index + 1) * minutes * 60_000 - 1,
      first_base_open_ms: start + index * minutes * 60_000, last_base_open_ms: start + (index + 1) * minutes * 60_000 - 60_000,
      component_count: minutes, expected_components: minutes })) as ReplayDisplayBar[];
    store.replace(window.map(replayDisplayBarToKline));
    const tailOpen = window.at(-1)!.open_time_ms;
    const forming = { ...window.at(-1)!, close: "321.25", high: "321.25", volume: "987.5",
      is_closed: false, last_base_open_ms: tailOpen, component_count: 1 };
    store.applyTick(replayDisplayBarToKline(forming));
    const tail = store.last()!;
    const current = { ...binding, sourceSequence: 7, forceInitialRefresh: true,
      revealedBoundaryMs: Number(tail.time) * 1000 + 123,
      identity: { ...binding.identity, source_kind: sourceKind, display_interval: `${minutes}m` } };
    let calls = 0;
    const source = new ReplayCanonicalIndicators(store, () => current, () => {}, async (url) => {
      calls++;
      const requestUrl = new URL(String(url), "http://fixture.test");
      if (sourceKind === "AGG_TRADE") {
        assert.ok(requestUrl.pathname.endsWith("/tape-projection"));
        assert.equal(requestUrl.searchParams.has("before_ms"), false);
        assert.equal(requestUrl.searchParams.get("source_sequence"), "7");
        return reply({ protocol: "replay.v3", schema_version: "replay.tape-projection.v1", run_id: "run",
          session_id: binding.sessionId, track_id: binding.trackId, identity: current.identity, data_epoch: dataEpoch,
          display_interval: current.identity.display_interval, history_scope: "CONTEXT_AND_FROZEN_TAPE",
          history_epoch: historyEpoch, history_policy: page([], start).history_policy,
          context_prepared_before_ms: 0, context_target_before_ms: 0, incomplete_context_buckets: [],
          revealed_boundary_ms: current.revealedBoundaryMs, source_sequence: 7, target_sequence: 7, prepared_sequence: 7,
          before_ms: null, history_boundary_ms: start, next_before_ms: start, has_more: false,
          status: "ready", bars: [...window.slice(0, 2), forming] });
      }
      assert.equal(requestUrl.searchParams.get("before_ms"), String(Number(tail.time) * 1000));
      return reply({ ...page(window.slice(0, 2), Number(tail.time) * 1000), identity: current.identity,
        revealed_boundary_ms: current.revealedBoundaryMs });
    }, noProjection);
    const request = job(store);
    await assert.rejects(source.compute({ jobs: [{ ...request, request: { ...request.request, interval: current.identity.display_interval } }] }), { name: "AbortError" });
    assert.equal(calls, 1);
    assert.deepEqual(store.last(), sourceKind === "AGG_TRADE" ? { ...tail, replayContextHistory: false } : tail);
    assert.equal(store.barCount, 3);
  }
});

test("a later trade at the same millisecond invalidates an old window refresh", async () => {
  const store = storeWith(), before = store.snapshot();
  let current = { ...binding, sourceSequence: 7, forceInitialRefresh: true };
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const source = new ReplayCanonicalIndicators(store, () => current, () => {}, async () => {
    await gate;
    return reply(page(sourceRows.slice(47, 50), sourceRows[50]!.open_time_ms));
  }, noProjection);
  const work = source.compute({ jobs: [job(store)] });
  current = { ...current, sourceSequence: 8 };
  finish();
  await assert.rejects(work, { name: "AbortError" });
  assert.deepEqual(store.snapshot(), before);
});

test("batch cancellation waits for sibling script cleanup before clearing progress", async () => {
  const store = storeWith();
  const progress: ReplayIndicatorPreparation[] = [];
  let finish!: () => void, stopped!: () => void;
  const cleanup = new Promise<void>(resolve => { finish = resolve; });
  const stopping = new Promise<void>(resolve => { stopped = resolve; });
  const source = new ReplayCanonicalIndicators(store, () => ({ ...binding, forceInitialRefresh: true }),
    value => progress.push(value), async () => reply(page(sourceRows.slice(47, 50), sourceRows[50]!.open_time_ms)), noProjection,
    async ({ signal }) => {
      await new Promise<void>(resolve => signal!.addEventListener("abort", () => resolve(), { once: true }));
      stopped(); await cleanup;
      throw new DOMException("script cleanup finished", "AbortError");
    });
  const script = { ...job(store, "script"), request: { ...job(store).request, mode: "script" as const, script: "plot(close)" } };
  let completed = false;
  const promise = source.compute({ jobs: [job(store), script] });
  void promise.then(() => { completed = true; }, () => { completed = true; });
  await stopping;
  assert.equal(completed, false);
  assert.equal(progress.at(-1)!.active, 1);
  finish();
  await assert.rejects(promise, { name: "AbortError" });
  assert.equal(progress.at(-1)!.active, 0);
});

test("canonical indicator retries only declared temporary archive errors with unchanged input", async () => {
  for (const retryable of [true, false]) {
    const store = storeWith(), requests: string[] = [];
    const source = new ReplayCanonicalIndicators(store, () => binding, () => {}, async (_url, options) => {
      requests.push(String(options?.body));
      return requests.length === 1 ? reply({ protocol: "replay.v3", error: {
        code: "HISTORY_SOURCE_UNAVAILABLE", message: "archive unavailable", details: { retryable },
      } }, 503) : reply(ready());
    }, noProjection);
    const result = await source.compute({ jobs: [job(store)] });
    assert.equal(requests.length, retryable ? 2 : 1);
    assert.equal(new Set(requests).size, 1);
    if (retryable) assert.equal(result.results[0]!.payload.error, null);
    else assert.match(result.results[0]!.payload.error!, /archive unavailable/);
  }
});

test("ready canonical results pass through the builtin cache before a slow sibling finishes", async () => {
  const store = storeWith();
  const progress: ReplayIndicatorPreparation[] = [];
  const seen: string[] = [];
  let finish!: () => void, firstReady!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const observed = new Promise<void>(resolve => { firstReady = resolve; });
  const source = new ReplayCanonicalIndicators(store, () => binding, value => progress.push(value), async (_url, init) => {
    const request = JSON.parse(String(init?.body)) as { params: { period?: number } };
    if (request.params.period === 20) await gate;
    return reply(ready());
  }, noProjection);
  const compute = createReplayBuiltinCompute(source.compute, { seedForPayload: source.seedForPayload, sourceKey: source.sourceKey });
  const fast = job(store), slow = { ...job(store, "slow"), request: { ...job(store).request, params: { period: 20 } } };
  const work = compute({ jobs: [fast, slow], onResults: results => { seen.push(...results.map(result => result.clientId)); firstReady(); } });
  await observed;
  assert.deepEqual(seen, ["rsi"]);
  assert.deepEqual(progress.at(-1)?.pendingIds, ["slow"]);
  finish();
  assert.equal((await work).results.length, 2);
  assert.deepEqual(seen, ["rsi", "slow"]);
  assert.deepEqual(progress.at(-1)?.pendingIds, []);
});
