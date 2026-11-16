import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { routeIndicatorComputeBatch } from "../frontendScriptBatch.js";
import { parseIndicatorPayloadEnvelope } from "../indicatorContracts.js";
import type { IndicatorComputeBatchExecutor } from "../indicatorComputeController.js";
import type { IndicatorComputeRequest, IndicatorValuePoint } from "../indicatorTypes.js";

const fixture = JSON.parse(readFileSync(new URL("../../replay/__tests__/fixtures/builtin-parity.json", import.meta.url), "utf8")) as {
  bars: IndicatorComputeRequest["ohlcv"];
  cases: { name: string; params: Record<string, unknown>; outputs: Record<string, IndicatorValuePoint[]>; seed: unknown; seed_count: number }[];
};
const reference = fixture.cases.find(item => item.name === "EMA" && Object.keys(item.params).length === 0)!;

test("live EMA validates once against Python, then advances repeated previews without HTTP", async () => {
  let requests = 0;
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => {
    requests++;
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey,
      payload: parseIndicatorPayloadEnvelope(reference.seed) })) };
  };
  for (let count = reference.seed_count; count <= fixture.bars.length; count++) {
    const rows = fixture.bars.slice(0, count).map((bar, index) => ({ ...bar, is_closed: index < count - 1 }));
    for (let preview = 0; preview < 2; preview++) {
      const result = await routeIndicatorComputeBatch({ jobs: [{ clientId: "chart-ema", jobKey: `${count}:${preview}`,
        request: { mode: "builtin", name: "EMA", interval: "1m", ohlcv: rows } }] }, remote);
      assert.deepEqual(result.results[0]!.payload.lines[0]!.data,
        reference.outputs.ema!.filter(point => point.time <= rows.at(-1)!.time));
    }
  }
  assert.equal(requests, 1);
  const corrected = fixture.bars.map(bar => ({ ...bar })); corrected[0]!.close += 1;
  await routeIndicatorComputeBatch({ jobs: [{ clientId: "chart-ema", jobKey: "correction",
    request: { mode: "builtin", name: "EMA", interval: "1m", ohlcv: corrected } }] }, remote);
  assert.equal(requests, 2, "a historical correction must be reseeded by the authority");
});

test("full series identity separates live EMA validation", async () => {
  let calls = 0;
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => {
    calls++;
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey,
      payload: parseIndicatorPayloadEnvelope(reference.seed) })) };
  };
  const rows = fixture.bars.slice(0, reference.seed_count);
  for (const providerId of ["a", "a", "b"]) {
    await routeIndicatorComputeBatch({ jobs: [{ clientId: "chart", jobKey: providerId,
      request: { mode: "builtin", name: "EMA", ohlcv: rows, seriesIdentity: { providerId } } }] }, remote);
  }
  assert.equal(calls, 2);
});

test("a validated builtin never relabels retired or other script execution as EMA", async () => {
  const languages: (string | undefined)[] = [];
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => ({ ok: true,
    results: jobs.map(job => {
      languages.push(job.request.language);
      return { clientId: job.clientId, jobKey: job.jobKey,
        payload: parseIndicatorPayloadEnvelope(job.request.language || job.request.script
          ? { ok: false, code: "PYNE_RETIRED", error: "Unsupported runtime", lines: [] }
          : reference.seed) };
    }),
  });
  const request: IndicatorComputeRequest = { mode: "builtin", name: "EMA",
    ohlcv: fixture.bars.slice(0, reference.seed_count) };
  const run = (request: IndicatorComputeRequest) => routeIndicatorComputeBatch({
    jobs: [{ clientId: "same-indicator", jobKey: "same-key", request }],
  }, remote);
  assert.equal((await run(request)).results[0]!.payload.ok, true);
  assert.equal((await run(request)).results[0]!.payload.ok, true);
  assert.deepEqual(languages, [undefined]);
  for (const scriptRequest of [{ language: "pyne" }, { language: " PyNe " },
    { language: "community-js" }, { script: "plot(close)" }]) {
    const result = await run({ ...request, ...scriptRequest });
    assert.equal(result.results[0]!.payload.ok, false);
  }
  assert.equal(languages.length, 5);
});

for (const gapAfter of [10, reference.seed_count - 1]) {
test(`Python-validated sparse live EMA seeds reuse an unchanged prefix (gap at ${gapAfter})`, async () => {
  let calls = 0;
  const shiftTime = (time: number) => time >= fixture.bars[gapAfter]!.time ? time + 60 : time;
  const seed = parseIndicatorPayloadEnvelope(reference.seed);
  const payload = { ...seed,
    lines: seed.lines.map(line => ({ ...line, data: line.data.map(point => ({ ...point, time: shiftTime(point.time) })) })),
    series: seed.series.map(series => ({ ...series, data: series.data.map(point => ({ ...point, time: shiftTime(point.time) })) })),
  };
  const remote: IndicatorComputeBatchExecutor = async ({ jobs }) => {
    calls++;
    return { ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) };
  };
  // Timestamp-only gaps preserve the one-shot Python EMA arithmetic from the
  // parity fixture. Canonical replay's reset/reseed contract stays separate.
  const bars = fixture.bars.map(bar => ({ ...bar, time: shiftTime(bar.time) }));
  for (let count = reference.seed_count; count <= bars.length; count++) {
    const result = await routeIndicatorComputeBatch({ jobs: [{ clientId: "sparse-live", jobKey: String(count),
      request: { mode: "builtin", name: "EMA", interval: "1m", ohlcv: bars.slice(0, count) } }] }, remote);
    assert.deepEqual(result.results[0]!.payload.lines[0]!.data,
      reference.outputs.ema!.filter(point => point.time <= fixture.bars[count - 1]!.time)
        .map(point => ({ ...point, time: shiftTime(point.time) })));
  }
  assert.equal(calls, 1, "a gap already validated by Python is not a new gap on every tick");
  const newlyGapped = [...bars, { ...bars.at(-1)!, time: bars.at(-1)!.time + 120 }];
  await routeIndicatorComputeBatch({ jobs: [{ clientId: "sparse-live", jobKey: "new-gap",
    request: { mode: "builtin", name: "EMA", interval: "1m", ohlcv: newlyGapped } }] }, remote);
  assert.equal(calls, 2, "a newly introduced gap still requires authoritative reseeding");
});
}
