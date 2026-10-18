import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createReplayBuiltinCompute, ReplayBuiltinState, roundBuiltinValue } from "../replayBuiltinCompute.js";
import type { ReplayBuiltinSeed } from "../replayBuiltinCompute.js";
import type { IndicatorComputeRequest, IndicatorPayloadEnvelope, IndicatorValuePoint } from "../../indicators/indicatorTypes.js";
import { parseIndicatorPayloadEnvelope } from "../../indicators/indicatorContracts.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/builtin-parity.json", import.meta.url), "utf8")) as {
  bars: IndicatorComputeRequest["ohlcv"];
  cases: { name: string; params: NonNullable<IndicatorComputeRequest["params"]>; outputs: Record<string, IndicatorValuePoint[]>; seed: unknown; seed_count: number;
    canonical: { prefix_count: number; initial_count: number; result: { payload: unknown; math_seed: ReplayBuiltinSeed } }[] }[];
};
const titles = { dif: "DIF", dea: "DEA", hist: "MACD Hist", vol: "VOL" };
for (const reference of fixture.cases) {
  const titleFor = (key: string) => key in titles ? titles[key as keyof typeof titles]
    : reference.name === "BOLL" ? ({ middle: `BOLL Mid(${reference.params.period ?? 20})`, upper: "BOLL Upper", lower: "BOLL Lower" })[key as "middle" | "upper" | "lower"]
    : `${reference.name}(${reference.params.period ?? (["EMA", "MA"].includes(reference.name) ? 20 : 14)})`;
  test(`incremental ${reference.name} ${JSON.stringify(reference.params)} matches Python builtin`, () => {
    const request = { mode: "builtin", name: reference.name, params: reference.params, ohlcv: fixture.bars };
    assert.equal(ReplayBuiltinState.supports(request), true);
    const state = new ReplayBuiltinState(request);
    for (let count = 1; count <= fixture.bars.length; count++) {
      assert.equal(state.advance(fixture.bars.slice(0, count)), true);
      // Repeated previews must not accumulate EMA or volume twice.
      assert.equal(state.advance(fixture.bars.slice(0, count)), true);
      for (const [key, expected] of Object.entries(reference.outputs)) {
        assert.deepEqual(state.points(titleFor(key)), expected.filter(p => p.time <= fixture.bars[count - 1]!.time));
      }
    }
    assert.equal(state.advance(fixture.bars.slice(0, 20)), false);
    const corrected = fixture.bars.map(bar => ({ ...bar }));
    corrected[0]!.close += 1;
    assert.equal(state.advance(corrected), false);
    const tail = fixture.bars.map(bar => ({ ...bar }));
    tail.at(-1)!.close += 3;
    assert.equal(state.advance(tail), true);
    const fresh = new ReplayBuiltinState({ ...request, ohlcv: tail });
    fresh.advance(tail);
    for (const key of Object.keys(reference.outputs)) assert.deepEqual(state.points(titleFor(key)), fresh.points(titleFor(key)));
  });
  test(`server-validated ${reference.name} ${JSON.stringify(reference.params)} advances from a real serialized seed`, async () => {
    let calls = 0;
    const compute = createReplayBuiltinCompute(async ({ jobs }) => {
      calls++;
      return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey,
        payload: parseIndicatorPayloadEnvelope(reference.seed) })) };
    });
    let payload: IndicatorPayloadEnvelope | undefined;
    for (let count = reference.seed_count; count <= fixture.bars.length; count++) {
      const rows = fixture.bars.slice(0, count).map((bar, i) => ({ ...bar, is_closed: i < count - 1 }));
      const response = await compute({ jobs: [{ clientId: "study", jobKey: String(count),
        request: { mode: "builtin", name: reference.name, params: reference.params, ohlcv: rows } }] });
      payload = response.results[0]?.payload;
    }
    assert.equal(calls, 1, "accepted builtins must retain recursive state across forming/closed boundaries");
    for (const [key, expected] of Object.entries(reference.outputs)) {
      assert.deepEqual(payload?.lines.find(line => line.name === titleFor(key) || line.title === titleFor(key))?.data, expected);
    }
  });
  test(`canonical-prefix ${reference.name} ${JSON.stringify(reference.params)} resumes before/during/after warmup`, async () => {
    for (const canonical of reference.canonical) {
      let calls = 0;
      let sourceKey = "first";
      const compute = createReplayBuiltinCompute(async ({ jobs }) => {
        calls++;
        return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey,
          payload: parseIndicatorPayloadEnvelope(canonical.result.payload) })) };
      }, { seedForPayload: () => canonical.result.math_seed, sourceKey: () => sourceKey });
      let payload: IndicatorPayloadEnvelope | undefined;
      for (let count = canonical.initial_count; count <= fixture.bars.length; count++) {
        const response = await compute({ jobs: [{ clientId: "study", jobKey: String(count), request: {
          mode: "builtin", name: reference.name, params: reference.params,
          ohlcv: fixture.bars.slice(canonical.prefix_count, count).map((bar, i, rows) => ({ ...bar, is_closed: i < rows.length - 1 })),
        } }] });
        payload = response.results[0]?.payload;
      }
      assert.equal(calls, 1, `${reference.name} prefix ${canonical.prefix_count} lost its initialized state`);
      const first = fixture.bars[canonical.prefix_count]!.time;
      for (const [key, expected] of Object.entries(reference.outputs)) {
        assert.deepEqual(payload?.lines.find(line => line.name === titleFor(key) || line.title === titleFor(key))?.data,
          expected.filter(point => point.time >= first));
      }
      sourceKey = "after-cache-release";
      await compute({ jobs: [{ clientId: "study", jobKey: "new-source", request: { mode: "builtin", name: reference.name,
        params: reference.params, ohlcv: fixture.bars.slice(canonical.prefix_count) } }] });
      assert.equal(calls, 2, "a changed history source must discard local recursive state");
    }
  });
}

test("script overrides and unsupported sources stay on the server", () => {
  assert.equal(ReplayBuiltinState.supports({ mode: "script", name: "MACD", ohlcv: fixture.bars }), false);
  assert.equal(ReplayBuiltinState.supports({ mode: "builtin", name: "MACD", params: { source: "unknown" }, ohlcv: fixture.bars }), false);
});

test("empty warmup and numerically different server implementations cannot validate a checkpoint", () => {
  for (const reference of fixture.cases) {
    const request = { mode: "builtin", name: reference.name, params: reference.params, ohlcv: fixture.bars };
    const state = new ReplayBuiltinState(request);
    state.advance(fixture.bars.slice(0, reference.seed_count));
    const payload = parseIndicatorPayloadEnvelope(reference.seed);
    assert.equal(state.matches(payload), true);
    assert.equal(state.matches({ ...payload, lines: payload.lines.map(line => ({ ...line, data: [] })) }), false);
    const altered = structuredClone(payload);
    altered.lines[0]!.data[0]!.value += 1e-8;
    assert.equal(state.matches(altered), false, `${reference.name} accepted a rounded-value mismatch`);
  }
});

test("builtin rounding preserves Python ties-to-even", () => {
  assert.equal(roundBuiltinValue(0.001953125), 0.00195312);
  assert.equal(roundBuiltinValue(-0.001953125), -0.00195312);
  assert.equal(roundBuiltinValue(0.005859375), 0.00585938);
});

test("incremental outputs reuse immutable prefixes without mutating earlier results", () => {
  const state = new ReplayBuiltinState({ mode: "builtin", name: "VOL", ohlcv: fixture.bars });
  state.advance(fixture.bars.slice(0, 10));
  const before = state.points("VOL");
  const expected = structuredClone(before);
  state.advance(fixture.bars.slice(0, 11));
  const after = state.points("VOL");
  assert.equal(after.length, 11);
  assert.strictEqual(after[0], before[0]);
  assert.ok(Object.isFrozen(after[0]));
  assert.deepEqual(before, expected);
  const revised = fixture.bars.slice(0, 11).map(bar => ({ ...bar }));
  revised[10]!.volume = 999;
  state.advance(revised);
  assert.equal(state.points("VOL").at(-1)?.value, 999);
  assert.equal(after.at(-1)?.value, 11);
});

test("validated tail calculations avoid HTTP; a history correction reseeds", async () => {
  let calls = 0;
  const compute = createReplayBuiltinCompute(async ({ jobs }) => {
    calls++;
    return { ok: true, results: jobs.map(job => {
      const payload: IndicatorPayloadEnvelope = {
        ok: true, lines: [{ name: "VOL", data: job.request.ohlcv.map(bar => ({ time: bar.time, value: bar.volume })) }],
        series: [], annotations: [], fills: [], legacyFills: [], markers: [], hlines: [],
        bgcolors: [], barcolors: [], signals: [], param_schema: [],
      };
      return { clientId: job.clientId, jobKey: job.jobKey, payload };
    }) };
  });
  const run = (rows: IndicatorComputeRequest["ohlcv"], key: string) => compute({ jobs: [{
    clientId: "vol", jobKey: key, request: { mode: "builtin", name: "VOL", ohlcv: rows },
  }] });
  await run(fixture.bars.slice(0, 10), "initial");
  const updated = await run(fixture.bars.slice(0, 11), "append");
  assert.equal(calls, 1);
  assert.equal(updated.results[0]!.payload.lines[0]!.data.length, 11);
  assert.equal(updated.results[0]!.payload.lines[0]!.colorData?.length, 11);
  const corrected = fixture.bars.slice(0, 11).map(bar => ({ ...bar }));
  corrected[0]!.volume++;
  await run(corrected, "correction");
  assert.equal(calls, 2);
});

test("a newly revealed gap reseeds instead of extending the previous mathematical window", () => {
  for (const name of ["MA", "BOLL", "RSI", "EMA", "ATR", "MACD"]) {
    const request = { mode: "builtin", name, interval: "1m", ohlcv: fixture.bars };
    const state = new ReplayBuiltinState(request);
    assert.equal(state.advance(fixture.bars.slice(0, 50)), true);
    assert.equal(state.advance([...fixture.bars.slice(0, 50), fixture.bars[51]!]), false);
  }
});

test("locally ready output publishes while a new remote study is pending", async () => {
  const reference = fixture.cases.find(item => item.name === "MA" && Object.keys(item.params).length === 0)!;
  const seen: string[] = [];
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  let requests = 0;
  const compute = createReplayBuiltinCompute(async ({ jobs }) => {
    requests++;
    if (requests > 1) await gate;
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: parseIndicatorPayloadEnvelope(reference.seed) })) };
  });
  const ma = { clientId: "ma", jobKey: "initial", request: { mode: "builtin", name: "MA", params: {}, ohlcv: fixture.bars.slice(0, reference.seed_count) } };
  await compute({ jobs: [ma] });
  const slow = { ...ma, clientId: "slow", jobKey: "slow", request: { ...ma.request, mode: "script", script: "plot(close)" } };
  const work = compute({ jobs: [{ ...ma, jobKey: "next" }, slow], onResults: results => seen.push(...results.map(result => result.clientId)) });
  assert.deepEqual(seen, ["ma"]);
  finish(); await work;
  assert.deepEqual(seen, ["ma", "slow"]);
});

test("finite maximum-period seeds match Python at small and very large prices", () => {
  const cases = (JSON.parse(readFileSync(new URL("./fixtures/builtin-parity.json", import.meta.url), "utf8")) as { finite: Array<{
    name: string; params: { period: number }; bars: IndicatorComputeRequest["ohlcv"];
    outputs: Record<string, IndicatorValuePoint[]>;
    canonical: { prefix_count: number; initial_count: number; result: { payload: unknown; math_seed: ReplayBuiltinSeed } }[];
  }> }).finite;
  for (const example of cases) for (const canonical of example.canonical) {
    const request = { mode: "builtin", name: example.name, params: example.params, interval: "1m", ohlcv: example.bars.slice(canonical.prefix_count, canonical.initial_count) };
    const state = new ReplayBuiltinState(request, canonical.result.math_seed);
    state.advance(request.ohlcv);
    assert.equal(state.matches(parseIndicatorPayloadEnvelope(canonical.result.payload)), true);
    for (let count = canonical.initial_count + 1; count <= example.bars.length; count++) {
      assert.equal(state.advance(example.bars.slice(canonical.prefix_count, count)), true);
    }
    for (const [key, expected] of Object.entries(example.outputs)) {
      const title = example.name === "MA" ? `MA(${example.params.period})`
        : { middle: `BOLL Mid(${example.params.period})`, upper: "BOLL Upper", lower: "BOLL Lower" }[key as "middle" | "upper" | "lower"];
      assert.deepEqual(state.points(title), expected.filter(point => point.time >= request.ohlcv[0]!.time));
    }
  }
});
