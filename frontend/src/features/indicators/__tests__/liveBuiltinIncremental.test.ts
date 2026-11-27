import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createLiveBuiltinCompute, roundBuiltinValue } from "../builtinIncrementalCompute.js";
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

const fixture = JSON.parse(readFileSync(new URL("../../replay/__tests__/fixtures/builtin-parity.json", import.meta.url), "utf8")) as {
  bars: IndicatorComputeRequest["ohlcv"];
  cases: { name: string; params: Record<string, unknown>; outputs: Record<string, IndicatorValuePoint[]>; seed: unknown; seed_count: number }[];
};
const reference = fixture.cases.find(item => item.name === "EMA" && Object.keys(item.params).length === 0)!;
const template = parseIndicatorPayloadEnvelope(reference.seed);
const run = (compute: IndicatorComputeBatchExecutor, request: IndicatorComputeRequest, jobKey = "job") =>
  routeIndicatorComputeBatch({ jobs: [{ clientId: "chart-ema", jobKey, request }] }, compute)
    .then(response => response.results[0]!.payload);
const emaPoints = (payload: IndicatorPayloadEnvelope) => payload.lines[0]!.data;

// Python round(x, 8) costs ~1 µs; the oracle recomputes whole windows per tick.
const rounded = new Map<number, number>();
const round8 = (value: number) => rounded.get(value) ?? (rounded.set(value, roundBuiltinValue(value)), rounded.get(value)!);

/** Independent full recompute: the Python builtin's SMA seed and recursion,
 * written out here instead of reusing the incremental state under test. */
function fullEma(rows: readonly IndicatorOhlcvBar[], period = 20, source = "close"): IndicatorValuePoint[] {
  const alpha = 2 / (period + 1);
  const value = (bar: IndicatorOhlcvBar) => source === "hl2" ? (bar.high + bar.low) / 2
    : source === "ohlc4" ? (bar.open + bar.high + bar.low + bar.close) / 4 : bar.close;
  const points: IndicatorValuePoint[] = [];
  let sum = 0, ema: number | null = null;
  rows.forEach((bar, index) => {
    if (index < period) { sum += value(bar); if (index === period - 1) ema = sum / period; }
    else ema = alpha * value(bar) + (1 - alpha) * ema!;
    if (ema !== null) points.push({ time: bar.time, value: round8(ema) });
  });
  return points;
}

/** Strict per-point equality; much cheaper than deepEqual on long series. */
function firstDifference(actual: readonly IndicatorValuePoint[], expected: readonly IndicatorValuePoint[]): string | null {
  if (actual.length !== expected.length) return `${actual.length} points, expected ${expected.length}`;
  const index = actual.findIndex((point, i) => point.time !== expected[i]!.time || !Object.is(point.value, expected[i]!.value));
  return index < 0 ? null : `point ${index}: ${JSON.stringify(actual[index])}, expected ${JSON.stringify(expected[index])}`;
}

/** The server's payload shape for a full recompute of exactly the given rows. */
function serverPayload(request: IndicatorComputeRequest): IndicatorPayloadEnvelope {
  const period = Number(request.params?.period ?? 20);
  const data = fullEma(request.ohlcv, period, String(request.params?.source ?? "close"));
  const title = `EMA(${period})`;
  return { ...template,
    lines: template.lines.map(line => ({ ...line, name: title, data })),
    series: template.series.map(series => ({ ...series, data, style: { ...series.style, title } })),
  };
}
function fullRecomputeServer() {
  const calls: IndicatorComputeRequest[] = [];
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => {
    calls.push(...jobs.map(job => job.request));
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: serverPayload(job.request) })) };
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

test("live EMA validates once against Python, then advances repeated previews without HTTP", async () => {
  let requests = 0;
  const live = createLiveBuiltinCompute(async ({ jobs }) => {
    requests++;
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: parseIndicatorPayloadEnvelope(reference.seed) })) };
  });
  for (let count = reference.seed_count; count <= fixture.bars.length; count++) {
    const rows = fixture.bars.slice(0, count).map((bar, index) => ({ ...bar, is_closed: index < count - 1 }));
    for (let preview = 0; preview < 2; preview++) {
      const payload = await run(live, { mode: "builtin", name: "EMA", interval: "1m", ohlcv: rows }, `${count}:${preview}`);
      // Python's own output for the same prefix is the authority.
      assert.deepEqual(emaPoints(payload), reference.outputs.ema!.filter(point => point.time <= rows.at(-1)!.time));
    }
  }
  assert.equal(requests, 1);
  const corrected = fixture.bars.map(bar => ({ ...bar })); corrected[0]!.close += 1;
  await run(live, { mode: "builtin", name: "EMA", interval: "1m", ohlcv: corrected }, "correction");
  assert.equal(requests, 2, "a historical correction must be reseeded by the authority");
});

test("oracle: every live EMA tick equals a full recompute of the same window", async () => {
  // The live local window is the trailing INDICATOR_HISTORY_LIMIT bars, as the
  // chart compute controller sends it. It first grows, then slides.
  const history = btcBars(INDICATOR_HISTORY_LIMIT + 120);
  for (const params of [{}, { period: 200 }, { period: 1, source: "hl2" }, { period: 50, source: "ohlc4" }]) {
    const { calls, remote } = fullRecomputeServer();
    const live = createLiveBuiltinCompute(remote);
    const next = random(11);
    const shown = history.slice(0, INDICATOR_HISTORY_LIMIT - 60).map(bar => ({ ...bar }));
    let ticks = 0, expectedRemote = 0;
    const tick = async (reason: string) => {
      const ohlcv = shown.slice(-INDICATOR_HISTORY_LIMIT).map(bar => ({ ...bar }));
      const before = calls.length;
      const payload = await run(live, { mode: "builtin", name: "EMA", interval: "1m", params, ohlcv }, String(++ticks));
      assert.equal(firstDifference(emaPoints(payload), fullEma(ohlcv, Number(params.period ?? 20), params.source)), null,
        `${JSON.stringify(params)} tick ${ticks} (${reason}) differs from a full recompute`);
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
        last.close = Math.round((last.open + (next() - 0.5) * 80) * 100) / 100;
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
    assert.ok(ticks > 4 * calls.length, `${JSON.stringify(params)}: ${ticks} ticks used ${calls.length} server computes`);
  }
});

for (const gapAfter of [10, reference.seed_count - 1]) {
  test(`Python-validated sparse live EMA seeds reuse an unchanged prefix (gap at ${gapAfter})`, async () => {
    let calls = 0;
    const shiftTime = (time: number) => time >= fixture.bars[gapAfter]!.time ? time + 60 : time;
    const payload = { ...template,
      lines: template.lines.map(line => ({ ...line, data: line.data.map(point => ({ ...point, time: shiftTime(point.time) })) })),
      series: template.series.map(series => ({ ...series, data: series.data.map(point => ({ ...point, time: shiftTime(point.time) })) })),
    };
    const live = createLiveBuiltinCompute(async ({ jobs }) => {
      calls++;
      return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) };
    });
    // Timestamp-only gaps keep the one-shot Python EMA arithmetic of the parity
    // fixture. Canonical replay's reset/reseed contract stays separate.
    const bars = fixture.bars.map(bar => ({ ...bar, time: shiftTime(bar.time) }));
    for (let count = reference.seed_count; count <= bars.length; count++) {
      const result = await run(live, { mode: "builtin", name: "EMA", interval: "1m", ohlcv: bars.slice(0, count) }, String(count));
      assert.deepEqual(emaPoints(result), reference.outputs.ema!.filter(point => point.time <= fixture.bars[count - 1]!.time)
        .map(point => ({ ...point, time: shiftTime(point.time) })));
      assert.deepEqual(emaPoints(result), fullEma(bars.slice(0, count)));
    }
    assert.equal(calls, 1, "a gap already validated by Python is not a new gap on every tick");
    const newlyGapped = [...bars, { ...bars.at(-1)!, time: bars.at(-1)!.time + 120 }];
    await run(live, { mode: "builtin", name: "EMA", interval: "1m", ohlcv: newlyGapped }, "new-gap");
    assert.equal(calls, 2, "a newly introduced gap still requires authoritative reseeding");
  });
}

test("full series identity separates live EMA validation", async () => {
  const { calls, remote } = fullRecomputeServer();
  const live = createLiveBuiltinCompute(remote);
  const rows = fixture.bars.slice(0, reference.seed_count);
  for (const providerId of ["a", "a", "b"]) {
    await run(live, { mode: "builtin", name: "EMA", ohlcv: rows, seriesIdentity: { providerId } }, providerId);
  }
  assert.equal(calls.length, 2);
});

test("an explicit recompute bypasses local state and revalidates", async () => {
  const { calls, remote } = fullRecomputeServer();
  const live = createLiveBuiltinCompute(remote);
  const request: IndicatorComputeRequest = { mode: "builtin", name: "EMA", interval: "1m", ohlcv: fixture.bars.slice(0, 60) };
  await run(live, request);
  await run(live, { ...request, ohlcv: fixture.bars.slice(0, 61) });
  assert.equal(calls.length, 1);
  await routeIndicatorComputeBatch({ force: true, jobs: [{ clientId: "chart-ema", jobKey: "forced", request }] }, live);
  assert.equal(calls.length, 2);
});

test("only EMA, and never replay or synthetic chart input, takes the live local path", async () => {
  const { calls, remote } = fullRecomputeServer();
  const live = createLiveBuiltinCompute(remote);
  const rows = fixture.bars.slice(0, 60);
  const requests: IndicatorComputeRequest[] = [
    { mode: "builtin", name: "MA", interval: "1m", ohlcv: rows },
    { mode: "builtin", name: "EMA", interval: "1m", ohlcv: rows,
      replayContext: { sessionId: "s", trackId: "t", dataEpoch: "e", revealedBoundaryMs: rows.at(-1)!.time * 1000 } },
    { mode: "builtin", name: "EMA", interval: "1m", ohlcv: rows, chartInput: { seriesId: "renko", generation: "g", revision: 1,
      request: {} as NonNullable<IndicatorComputeRequest["chartInput"]>["request"] } },
  ];
  for (const request of requests) {
    for (let repeat = 0; repeat < 2; repeat++) await run(live, request, `${request.name}:${repeat}`);
  }
  assert.equal(calls.length, requests.length * 2);
});

test("a validated builtin never relabels retired or other script execution as EMA", async () => {
  const languages: (string | undefined)[] = [];
  const live = createLiveBuiltinCompute(async ({ jobs }) => ({ ok: true,
    results: jobs.map(job => {
      languages.push(job.request.language);
      return { clientId: job.clientId, jobKey: job.jobKey,
        payload: job.request.language || job.request.script
          ? parseIndicatorPayloadEnvelope({ ok: false, code: "PYNE_RETIRED", error: "Unsupported runtime", lines: [] })
          : parseIndicatorPayloadEnvelope(reference.seed) };
    }),
  }));
  const request: IndicatorComputeRequest = { mode: "builtin", name: "EMA", ohlcv: fixture.bars.slice(0, reference.seed_count) };
  assert.equal((await run(live, request)).ok, true);
  assert.equal((await run(live, request)).ok, true);
  assert.deepEqual(languages, [undefined]);
  for (const scriptRequest of [{ language: "pyne" }, { language: " PyNe " }, { language: "community-js" }, { script: "plot(close)" }]) {
    assert.equal((await run(live, { ...request, ...scriptRequest })).ok, false);
  }
  assert.equal(languages.length, 5);
});

test("replay keeps its strict defaults: only revealed rows, no sparse seeds", async () => {
  const { calls, remote } = fullRecomputeServer();
  const replay = createReplayBuiltinCompute(remote);
  const bars = btcBars(400);
  const reveal = (count: number) => run(replay, { mode: "builtin", name: "EMA", interval: "1m",
    ohlcv: bars.slice(0, count).map((bar, index) => ({ ...bar, is_closed: index < count - 1 })) }, String(count));
  for (let count = 100; count <= 300; count++) {
    const payload = await reveal(count);
    assert.deepEqual(emaPoints(payload), fullEma(bars.slice(0, count)));
  }
  assert.equal(calls.length, 1);
  // A rewind is a new, shorter input: the server recomputes it and nothing
  // computed for later bars survives in the result.
  const rewound = await reveal(150);
  assert.equal(calls.length, 2);
  assert.ok(emaPoints(rewound).every(point => point.time <= bars[149]!.time));
  assert.deepEqual(emaPoints(rewound), fullEma(bars.slice(0, 150)));
  // Replay never accepts a sparse seed: a gapped input stays on the server.
  const gapped = bars.slice(0, 120).map((bar, index) => ({ ...bar, time: index >= 60 ? bar.time + 60 : bar.time }));
  for (let count = 100; count <= 103; count++) {
    await run(replay, { mode: "builtin", name: "EMA", interval: "1m", ohlcv: gapped.slice(0, count) }, `gap:${count}`);
  }
  assert.equal(calls.length, 6);
});

test("the workspace data manager advances live EMA locally and forwards an explicit recompute", async t => {
  const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
  const bars = btcBars(240);
  const cached = bars as unknown as KlineBar[];
  const cache = new SharedMarketCache();
  const token = cache.beginRead(series);
  cache.admitResponse(token, { data: cached.slice(0, 200), endpoint: "history" });
  token.release();
  const gate = new ForegroundPreloadGate(0);
  const { calls, remote } = fullRecomputeServer();
  const manager = new IndicatorDataManager({ cache, gate, coalesceMs: 0, backendCompute: remote });
  t.after(() => { manager.dispose(); gate.dispose(); });
  const compute = async (rows: IndicatorOhlcvBar[], force = false) => (await manager.compute({ force,
    jobs: [{ clientId: "ema", jobKey: "ema", request: { ...series, mode: "builtin", name: "EMA", ohlcv: rows } }] })).results[0]!.payload;
  for (let count = 200; count <= 240; count++) {
    if (count > 200) {
      const update = cache.beginRead(series);
      cache.admitResponse(update, { data: cached.slice(count - 1, count), endpoint: "history" });
      update.release();
    }
    assert.deepEqual(emaPoints(await compute(bars.slice(0, count))), fullEma(bars.slice(0, count)));
  }
  assert.equal(calls.length, 1, "growing closed input advances without the server");
  assert.ok(calls.every(request => !("forceBuiltinValidation" in request)), "the force flag stays off the wire");
  await compute(bars.slice(0, 240), true);
  assert.equal(calls.length, 2, "an explicit recompute reaches the server");
});
