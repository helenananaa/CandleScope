import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createReplayBuiltinCompute, ReplayBuiltinState, roundBuiltinValue } from "../replayBuiltinCompute.js";
import type { IndicatorComputeRequest, IndicatorPayloadEnvelope, IndicatorValuePoint } from "../../indicators/indicatorTypes.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/builtin-parity.json", import.meta.url), "utf8")) as {
  bars: IndicatorComputeRequest["ohlcv"];
  cases: { name: string; params: NonNullable<IndicatorComputeRequest["params"]>; outputs: Record<string, IndicatorValuePoint[]> }[];
};
const titles = { dif: "DIF", dea: "DEA", hist: "MACD Hist", vol: "VOL" };
for (const reference of fixture.cases) {
  test(`incremental ${reference.name} ${JSON.stringify(reference.params)} matches Python builtin`, () => {
    const request = { mode: "builtin", name: reference.name, params: reference.params, ohlcv: fixture.bars };
    assert.equal(ReplayBuiltinState.supports(request), true);
    const state = new ReplayBuiltinState(request);
    for (let count = 1; count <= fixture.bars.length; count++) {
      assert.equal(state.advance(fixture.bars.slice(0, count)), true);
      // Repeated previews must not accumulate EMA or volume twice.
      assert.equal(state.advance(fixture.bars.slice(0, count)), true);
      for (const [key, expected] of Object.entries(reference.outputs)) {
        assert.deepEqual(state.points(titles[key as keyof typeof titles]), expected.filter(p => p.time <= fixture.bars[count - 1]!.time));
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
    for (const title of Object.values(titles)) assert.deepEqual(state.points(title), fresh.points(title));
  });
}

test("script overrides and unsupported sources stay on the server", () => {
  assert.equal(ReplayBuiltinState.supports({ mode: "script", name: "MACD", ohlcv: fixture.bars }), false);
  assert.equal(ReplayBuiltinState.supports({ mode: "builtin", name: "MACD", params: { source: "unknown" }, ohlcv: fixture.bars }), false);
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
