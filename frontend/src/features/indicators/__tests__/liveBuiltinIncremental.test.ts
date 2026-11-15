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

test("full series identity separates live EMA validation and unverified outputs stay remote", async () => {
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
