import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createLiveBuiltinCompute, LIVE_INCREMENTAL_BUILTINS, roundBuiltinValue } from "../builtinIncrementalCompute.js";
import { createReplayBuiltinCompute } from "../../replay/replayBuiltinCompute.js";
import { routeIndicatorComputeBatch } from "../frontendScriptBatch.js";
import { parseIndicatorPayloadEnvelope } from "../indicatorContracts.js";
import { INDICATOR_HISTORY_LIMIT } from "../indicatorComputeRuntime.js";
import { IndicatorDataManager } from "../indicatorDataManager.js";
import type { IndicatorComputeBatchExecutor } from "../indicatorComputeController.js";
import type { IndicatorComputeRequest, IndicatorOhlcvBar, IndicatorPayloadEnvelope, IndicatorValuePoint } from "../indicatorTypes.js";
import { SharedMarketCache } from "../../market-data/manager/sharedMarketCache.js";
import { ForegroundPreloadGate } from "../../market-data/foregroundPreloadGate.js";
import type { KlineBar } from "../../market-data/marketDataTypes.js";

type Params = NonNullable<IndicatorComputeRequest["params"]>;
type FixtureCase = { name: string; params: Params; outputs: Record<string, IndicatorValuePoint[]>; seed: unknown; seed_count: number };
const fixture = JSON.parse(readFileSync(new URL("../../replay/__tests__/fixtures/builtin-parity.json", import.meta.url), "utf8")) as {
  bars: IndicatorComputeRequest["ohlcv"];
  cases: FixtureCase[];
};
const LIVE = ["EMA", "MA", "RSI"] as const;
type LiveName = typeof LIVE[number];
const defaultCase = (name: string) => fixture.cases.find(item => item.name === name && Object.keys(item.params).length === 0)!;
const templates = Object.fromEntries(LIVE.map(name => [name, parseIndicatorPayloadEnvelope(defaultCase(name).seed)])) as Record<LiveName, IndicatorPayloadEnvelope>;
const periodOf = (name: string, params: Params = {}) => Number(params.period ?? (name === "RSI" ? 14 : 20));
const titleOf = (name: string, params: Params = {}) => `${name}(${periodOf(name, params)})`;
const run = (compute: IndicatorComputeBatchExecutor, request: IndicatorComputeRequest, jobKey = "job") =>
  routeIndicatorComputeBatch({ jobs: [{ clientId: `chart-${request.name}`, jobKey, request }] }, compute)
    .then(response => response.results[0]!.payload);
const linePoints = (payload: IndicatorPayloadEnvelope) => payload.lines[0]!.data;

// Python round(x, 8) costs ~1 µs; the oracle recomputes whole windows per tick.
const rounded = new Map<number, number>();
const round8 = (value: number) => rounded.get(value) ?? (rounded.set(value, roundBuiltinValue(value)), rounded.get(value)!);

// Independent full recomputes, written from the Python builtins
// (app/indicator/indicators/{ema,ma,rsi}.py, BaseIndicator._get_field and
// window_math.py) instead of reusing the incremental state under test.
function sourceValue(bar: IndicatorOhlcvBar, source = "close"): number {
  if (source === "hl2") return (bar.high + bar.low) / 2;
  if (source === "hlc3") return (bar.high + bar.low + bar.close) / 3;
  if (source === "ohlc4") return (bar.open + bar.high + bar.low + bar.close) / 4;
  return bar[source as "open" | "high" | "low" | "close"];
}
/** Neumaier summation from zero of values[start..end) - shift:
 * window_math.compensated_sum, and also what Python 3.12's builtin sum()
 * does for a list of floats. */
function neumaierSum(values: readonly number[], start = 0, end = values.length, shift = 0): number {
  let total = 0, correction = 0;
  for (let index = start; index < end; index++) {
    const value = values[index]! - shift;
    const next = total + value;
    correction += Math.abs(total) >= Math.abs(value) ? (total - next) + value : (value - next) + total;
    total = next;
  }
  return total + correction;
}
function fullEma(rows: readonly IndicatorOhlcvBar[], period = 20, source = "close"): IndicatorValuePoint[] {
  const alpha = 2 / (period + 1);
  const points: IndicatorValuePoint[] = [];
  let sum = 0, ema: number | null = null;
  rows.forEach((bar, index) => {
    if (index < period) { sum += sourceValue(bar, source); if (index === period - 1) ema = sum / period; }
    else ema = alpha * sourceValue(bar, source) + (1 - alpha) * ema!;
    if (ema !== null) points.push({ time: bar.time, value: round8(ema) });
  });
  return points;
}
/** window_math.window_mean over each complete trailing window. */
function fullMa(rows: readonly IndicatorOhlcvBar[], period = 20, source = "close"): IndicatorValuePoint[] {
  const values = rows.map(bar => sourceValue(bar, source));
  const points: IndicatorValuePoint[] = [];
  for (let index = period - 1; index < rows.length; index++) {
    const start = index - period + 1, anchor = values[start]!;
    points.push({ time: rows[index]!.time, value: round8(anchor + neumaierSum(values, start, index + 1, anchor) / period) });
  }
  return points;
}
/** Wilder RSI: the first `period` changes seed sum()/period, then recursion. */
function fullRsi(rows: readonly IndicatorOhlcvBar[], period = 14, source = "close"): IndicatorValuePoint[] {
  const points: IndicatorValuePoint[] = [];
  const gains: number[] = [], losses: number[] = [];
  let previous: number | null = null, gain = 0, loss = 0;
  rows.forEach((bar, index) => {
    const value = sourceValue(bar, source);
    if (previous === null) { previous = value; return; }
    const change = value - previous;
    previous = value;
    if (index <= period) {
      gains.push(Math.max(change, 0)); losses.push(Math.max(-change, 0));
      if (index < period) return;
      gain = neumaierSum(gains) / period; loss = neumaierSum(losses) / period;
    } else {
      gain = (gain * (period - 1) + Math.max(change, 0)) / period;
      loss = (loss * (period - 1) + Math.max(-change, 0)) / period;
    }
    points.push({ time: bar.time, value: round8(loss === 0 ? 100 : 100 - 100 / (1 + gain / loss)) });
  });
  return points;
}
function fullRecompute(name: string, rows: readonly IndicatorOhlcvBar[], params: Params = {}): IndicatorValuePoint[] {
  const full = name === "EMA" ? fullEma : name === "MA" ? fullMa : name === "RSI" ? fullRsi : undefined;
  if (!full) throw new Error(`no oracle for ${name}`);
  return full(rows, periodOf(name, params), String(params.source ?? "close"));
}

/** Strict per-point equality; much cheaper than deepEqual on long series. */
function firstDifference(actual: readonly IndicatorValuePoint[], expected: readonly IndicatorValuePoint[]): string | null {
  if (actual.length !== expected.length) return `${actual.length} points, expected ${expected.length}`;
  const index = actual.findIndex((point, i) => point.time !== expected[i]!.time || !Object.is(point.value, expected[i]!.value));
  return index < 0 ? null : `point ${index}: ${JSON.stringify(actual[index])}, expected ${JSON.stringify(expected[index])}`;
}

/** The server's payload shape for a full recompute of exactly the given rows. */
function serverPayload(request: IndicatorComputeRequest): IndicatorPayloadEnvelope {
  const template = templates[request.name as LiveName];
  const data = fullRecompute(request.name!, request.ohlcv, request.params);
  const title = titleOf(request.name!, request.params);
  return { ...template,
    lines: template.lines.map(line => ({ ...line, name: title, data })),
    series: template.series.map(series => ({ ...series, data, style: { ...series.style, title } })),
  };
}
function fullRecomputeServer() {
  const calls: IndicatorComputeRequest[] = [];
  let batches = 0;
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => {
    batches++;
    calls.push(...jobs.map(job => job.request));
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: serverPayload(job.request) })) };
  };
  return { calls, remote, batches: () => batches };
}
/** Replies with the Python parity fixture's own serialized payload. */
function fixtureServer(payloadFor: (request: IndicatorComputeRequest) => unknown) {
  const calls: IndicatorComputeRequest[] = [];
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => {
    calls.push(...jobs.map(job => job.request));
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey,
      payload: parseIndicatorPayloadEnvelope(payloadFor(job.request)) })) };
  };
  return { calls, remote };
}

/** Seeded so a failure reproduces. */
function random(seed: number) {
  return () => { seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648; return seed / 2_147_483_648; };
}
function btcBars(count: number, next = random(7)): IndicatorOhlcvBar[] {
  let close = 91_234.56;
  return Array.from({ length: count }, (_, index) => {
    const open = close;
    close = Math.round((open + (next() - 0.5) * 120) * 100) / 100;
    return { time: 1_764_000_000 + index * 60, open, close, volume: Math.round(next() * 5_000) / 1_000,
      high: Math.max(open, close) + Math.round(next() * 4_000) / 100, low: Math.min(open, close) - Math.round(next() * 4_000) / 100,
      is_closed: true };
  });
}

test("the live local builtins are exactly EMA, MA and RSI", () => {
  assert.deepEqual([...LIVE_INCREMENTAL_BUILTINS].sort(), [...LIVE].sort());
});

for (const reference of fixture.cases.filter(item => LIVE_INCREMENTAL_BUILTINS.has(item.name))) {
  test(`live ${reference.name} ${JSON.stringify(reference.params)} validates once against Python, then advances previews without HTTP`, async () => {
    const { calls, remote } = fixtureServer(() => reference.seed);
    const live = createLiveBuiltinCompute(remote);
    const expected = reference.outputs[reference.name.toLowerCase()]!;
    for (let count = reference.seed_count; count <= fixture.bars.length; count++) {
      const rows = fixture.bars.slice(0, count).map((bar, index) => ({ ...bar, is_closed: index < count - 1 }));
      for (let preview = 0; preview < 2; preview++) {
        const payload = await run(live, { mode: "builtin", name: reference.name, params: reference.params, interval: "1m", ohlcv: rows }, `${count}:${preview}`);
        // Python's own output for the same prefix is the authority.
        assert.deepEqual(linePoints(payload), expected.filter(point => point.time <= rows.at(-1)!.time));
        assert.equal(payload.lines[0]!.name, titleOf(reference.name, reference.params));
      }
    }
    assert.equal(calls.length, 1);
    const corrected = fixture.bars.map(bar => ({ ...bar })); corrected[0]!.close += 1;
    await run(live, { mode: "builtin", name: reference.name, params: reference.params, interval: "1m", ohlcv: corrected }, "correction");
    assert.equal(calls.length, 2, "a historical correction must be reseeded by the authority");
  });
}

const ORACLE_PARAMS: Record<LiveName, Params[]> = {
  EMA: [{}, { period: 200 }, { period: 1, source: "hl2" }, { period: 50, source: "ohlc4" }],
  MA: [{}, { period: 200, source: "hlc3" }, { period: 1, source: "hl2" }, { period: 50, source: "ohlc4" }],
  RSI: [{}, { period: 2, source: "hlc3" }, { period: 100, source: "ohlc4" }, { period: 21, source: "open" }],
};
for (const name of LIVE) {
  test(`oracle: every live ${name} tick equals a full recompute of the same window`, async () => {
    // The live local window is the trailing INDICATOR_HISTORY_LIMIT bars, as the
    // chart compute controller sends it. It first grows, then slides.
    const history = btcBars(INDICATOR_HISTORY_LIMIT + 120);
    for (const params of ORACLE_PARAMS[name]) {
      const { calls, remote } = fullRecomputeServer();
      const live = createLiveBuiltinCompute(remote);
      const next = random(11);
      const shown = history.slice(0, INDICATOR_HISTORY_LIMIT - 60).map(bar => ({ ...bar }));
      let ticks = 0, expectedRemote = 0;
      const tick = async (reason: string) => {
        const ohlcv = shown.slice(-INDICATOR_HISTORY_LIMIT).map(bar => ({ ...bar }));
        const before = calls.length;
        const payload = await run(live, { mode: "builtin", name, interval: "1m", params, ohlcv }, String(++ticks));
        assert.equal(firstDifference(linePoints(payload), fullRecompute(name, ohlcv, params)), null,
          `${name} ${JSON.stringify(params)} tick ${ticks} (${reason}) differs from a full recompute`);
        return calls.length - before;
      };
      assert.equal(await tick("first load"), 1);
      expectedRemote++;
      for (let index = shown.length; index < history.length; index++) {
        const bar = history[index]!;
        const sliding = shown.length >= INDICATOR_HISTORY_LIMIT;
        shown.push({ ...bar, close: bar.open, high: bar.open, low: bar.open, volume: 0, is_closed: false });
        // A new candle moves a full window: the server validates the new window once.
        assert.equal(await tick("new candle"), sliding ? 1 : 0);
        if (sliding) expectedRemote++;
        for (let preview = 0; preview < 3; preview++) {
          const last = shown.at(-1)!;
          // Every few ticks the price returns to the open: RSI sees a zero change.
          last.close = preview === 1 && index % 7 === 0 ? last.open : Math.round((last.open + (next() - 0.5) * 80) * 100) / 100;
          last.high = Math.max(last.high, last.close); last.low = Math.min(last.low, last.close); last.volume += 0.25;
          assert.equal(await tick("forming tick"), 0, "a forming tick must not call the server");
        }
        Object.assign(shown.at(-1)!, bar, { is_closed: true });
        assert.equal(await tick("candle closed"), 0, "closing the forming candle must not call the server");
        if (index % 41 === 0) {
          // Backfill or an exchange amendment changes an already closed bar.
          shown.at(-3)!.close += 0.5;
          assert.equal(await tick("closed bar amended"), 1);
          expectedRemote++;
        }
      }
      assert.equal(calls.length, expectedRemote);
      assert.ok(ticks > 4 * calls.length, `${name} ${JSON.stringify(params)}: ${ticks} ticks used ${calls.length} server computes`);
    }
  });
}

test("oracle: a flat market keeps RSI at 100 locally, as Python does when losses are zero", async () => {
  const { calls, remote } = fullRecomputeServer();
  const live = createLiveBuiltinCompute(remote);
  const rows = btcBars(40).map(bar => ({ ...bar, open: 100, high: 100, low: 100, close: 100 }));
  for (let count = 20; count <= rows.length; count++) {
    const payload = await run(live, { mode: "builtin", name: "RSI", interval: "1m", ohlcv: rows.slice(0, count) }, String(count));
    assert.deepEqual(linePoints(payload), fullRsi(rows.slice(0, count)));
    assert.ok(linePoints(payload).every(point => point.value === 100));
  }
  assert.equal(calls.length, 1);
});

for (const name of LIVE) {
  const reference = defaultCase(name);
  for (const gapAfter of [10, reference.seed_count - 1]) {
    test(`Python-validated sparse live ${name} seeds reuse an unchanged prefix (gap at ${gapAfter})`, async () => {
      const shiftTime = (time: number) => time >= fixture.bars[gapAfter]!.time ? time + 60 : time;
      const template = templates[name];
      const payload = { ...template,
        lines: template.lines.map(line => ({ ...line, data: line.data.map(point => ({ ...point, time: shiftTime(point.time) })) })),
        series: template.series.map(series => ({ ...series, data: series.data.map(point => ({ ...point, time: shiftTime(point.time) })) })),
      };
      const { calls, remote } = fixtureServer(() => payload);
      const live = createLiveBuiltinCompute(remote);
      // Timestamp-only gaps keep the one-shot Python arithmetic of the parity
      // fixture. Canonical replay's reset/reseed contract stays separate.
      const bars = fixture.bars.map(bar => ({ ...bar, time: shiftTime(bar.time) }));
      for (let count = reference.seed_count; count <= bars.length; count++) {
        const result = await run(live, { mode: "builtin", name, interval: "1m", ohlcv: bars.slice(0, count) }, String(count));
        assert.deepEqual(linePoints(result), reference.outputs[name.toLowerCase()]!.filter(point => point.time <= fixture.bars[count - 1]!.time)
          .map(point => ({ ...point, time: shiftTime(point.time) })));
        assert.deepEqual(linePoints(result), fullRecompute(name, bars.slice(0, count)));
      }
      assert.equal(calls.length, 1, "a gap already validated by Python is not a new gap on every tick");
      const newlyGapped = [...bars, { ...bars.at(-1)!, time: bars.at(-1)!.time + 120 }];
      await run(live, { mode: "builtin", name, interval: "1m", ohlcv: newlyGapped }, "new-gap");
      assert.equal(calls.length, 2, "a newly introduced gap still requires authoritative reseeding");
    });
  }
}

test("full series identity separates live builtin validation", async () => {
  const { calls, remote } = fullRecomputeServer();
  const live = createLiveBuiltinCompute(remote);
  const rows = fixture.bars.slice(0, 40);
  for (const name of LIVE) {
    for (const providerId of ["a", "a", "b"]) {
      await run(live, { mode: "builtin", name, ohlcv: rows, seriesIdentity: { providerId } }, `${name}:${providerId}`);
    }
  }
  assert.equal(calls.length, 2 * LIVE.length);
});

test("an explicit recompute bypasses local state and revalidates", async () => {
  for (const name of LIVE) {
    const { calls, remote } = fullRecomputeServer();
    const live = createLiveBuiltinCompute(remote);
    const request: IndicatorComputeRequest = { mode: "builtin", name, interval: "1m", ohlcv: fixture.bars.slice(0, 60) };
    await run(live, request);
    await run(live, { ...request, ohlcv: fixture.bars.slice(0, 61) });
    assert.equal(calls.length, 1, name);
    await routeIndicatorComputeBatch({ force: true, jobs: [{ clientId: `chart-${name}`, jobKey: "forced", request }] }, live);
    assert.equal(calls.length, 2, name);
  }
});

test("only EMA, MA and RSI, and never replay or synthetic chart input, take the live local path", async () => {
  // Each request gets the Python fixture payload that would validate it, so
  // only the routing filter can keep it on the server.
  const caseFor = (request: IndicatorComputeRequest) => defaultCase(request.name!);
  const { calls, remote } = fixtureServer(request => caseFor(request).seed);
  const live = createLiveBuiltinCompute(remote);
  const rows = (name: string) => fixture.bars.slice(0, defaultCase(name).seed_count);
  const replayContext = (name: string) => ({ sessionId: "s", trackId: "t", dataEpoch: "e", revealedBoundaryMs: rows(name).at(-1)!.time * 1000 });
  const chartInput = { seriesId: "renko", generation: "g", revision: 1, request: {} as NonNullable<IndicatorComputeRequest["chartInput"]>["request"] };
  const remoteOnly: IndicatorComputeRequest[] = [
    ...["BOLL", "MACD", "ATR", "VOL"].map(name => ({ mode: "builtin", name, ohlcv: rows(name) })),
    ...LIVE.map(name => ({ mode: "builtin", name, interval: "1m", ohlcv: rows(name), replayContext: replayContext(name) })),
    ...LIVE.map(name => ({ mode: "builtin", name, interval: "1m", ohlcv: rows(name), chartInput })),
  ];
  for (const request of remoteOnly) {
    for (let repeat = 0; repeat < 2; repeat++) await run(live, request, `${request.name}:${repeat}`);
  }
  assert.equal(calls.length, remoteOnly.length * 2);
  for (const name of LIVE) {
    for (let repeat = 0; repeat < 2; repeat++) await run(live, { mode: "builtin", name, ohlcv: rows(name) }, `${name}:local:${repeat}`);
  }
  assert.equal(calls.length, remoteOnly.length * 2 + LIVE.length, "a validated EMA, MA or RSI repeats locally");
});

test("a validated builtin never relabels retired or other script execution as a builtin", async () => {
  for (const name of LIVE) {
    const languages: (string | undefined)[] = [];
    const reference = defaultCase(name);
    const live = createLiveBuiltinCompute(async ({ jobs }) => ({ ok: true,
      results: jobs.map(job => {
        languages.push(job.request.language);
        return { clientId: job.clientId, jobKey: job.jobKey,
          payload: job.request.language || job.request.script
            ? parseIndicatorPayloadEnvelope({ ok: false, code: "PYNE_RETIRED", error: "Unsupported runtime", lines: [] })
            : parseIndicatorPayloadEnvelope(reference.seed) };
      }),
    }));
    const request: IndicatorComputeRequest = { mode: "builtin", name, ohlcv: fixture.bars.slice(0, reference.seed_count) };
    assert.equal((await run(live, request)).ok, true);
    assert.equal((await run(live, request)).ok, true);
    assert.deepEqual(languages, [undefined]);
    for (const scriptRequest of [{ language: "pyne" }, { language: " PyNe " }, { language: "community-js" }, { script: "plot(close)" }]) {
      assert.equal((await run(live, { ...request, ...scriptRequest })).ok, false, `${name} ${JSON.stringify(scriptRequest)}`);
    }
    assert.equal(languages.length, 5);
  }
});

test("replay keeps its strict defaults: only revealed rows, no sparse seeds", async () => {
  for (const name of LIVE) {
    const { calls, remote } = fullRecomputeServer();
    const replay = createReplayBuiltinCompute(remote);
    const bars = btcBars(400);
    const reveal = (count: number) => run(replay, { mode: "builtin", name, interval: "1m",
      ohlcv: bars.slice(0, count).map((bar, index) => ({ ...bar, is_closed: index < count - 1 })) }, String(count));
    for (let count = 100; count <= 300; count++) {
      const payload = await reveal(count);
      assert.deepEqual(linePoints(payload), fullRecompute(name, bars.slice(0, count)));
    }
    assert.equal(calls.length, 1, name);
    // A rewind is a new, shorter input: the server recomputes it and nothing
    // computed for later bars survives in the result.
    const rewound = await reveal(150);
    assert.equal(calls.length, 2, name);
    assert.ok(linePoints(rewound).every(point => point.time <= bars[149]!.time));
    assert.deepEqual(linePoints(rewound), fullRecompute(name, bars.slice(0, 150)));
    // Replay never accepts a sparse seed: a gapped input stays on the server.
    const gapped = bars.slice(0, 120).map((bar, index) => ({ ...bar, time: index >= 60 ? bar.time + 60 : bar.time }));
    for (let count = 100; count <= 103; count++) {
      await run(replay, { mode: "builtin", name, interval: "1m", ohlcv: gapped.slice(0, count) }, `gap:${count}`);
    }
    assert.equal(calls.length, 6, name);
  }
});

test("the workspace data manager advances the default MA and RSI locally and forwards an explicit recompute", async t => {
  const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const bars = btcBars(240);
  const cached = bars as unknown as KlineBar[];
  const cache = new SharedMarketCache();
  const token = cache.beginRead(series);
  cache.admitResponse(token, { data: cached.slice(0, 200), endpoint: "history" });
  token.release();
  const gate = new ForegroundPreloadGate(0);
  const { calls, remote, batches } = fullRecomputeServer();
  const manager = new IndicatorDataManager({ cache, gate, coalesceMs: 0, backendCompute: remote });
  t.after(() => { manager.dispose(); gate.dispose(); });
  // App.tsx's default live chart indicators, plus an EMA in the same batch.
  const indicators: { name: LiveName; params: Params }[] = [
    { name: "MA", params: { period: 20 } }, { name: "RSI", params: { period: 14 } }, { name: "EMA", params: {} }];
  const compute = async (rows: IndicatorOhlcvBar[], force = false) => (await manager.compute({ force,
    jobs: indicators.map(({ name, params }) => ({ clientId: name, jobKey: name,
      request: { ...series, mode: "builtin", name, params, ohlcv: rows } })) })).results.map(item => item.payload);
  for (let count = 200; count <= 240; count++) {
    if (count > 200) {
      const update = cache.beginRead(series);
      cache.admitResponse(update, { data: cached.slice(count - 1, count), endpoint: "history" });
      update.release();
    }
    const payloads = await compute(bars.slice(0, count));
    indicators.forEach(({ name, params }, index) => {
      assert.deepEqual(linePoints(payloads[index]!), fullRecompute(name, bars.slice(0, count), params), `${name} at ${count}`);
    });
  }
  assert.equal(calls.length, indicators.length, "growing closed input advances without the server");
  assert.equal(batches(), 1, "the first load validates all three in one batch");
  assert.ok(calls.every(request => !("forceBuiltinValidation" in request)), "the force flag stays off the wire");
  await compute(bars.slice(0, 240), true);
  assert.equal(calls.length, 2 * indicators.length, "an explicit recompute reaches the server");
});
