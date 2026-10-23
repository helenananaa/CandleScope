import assert from "node:assert/strict";
import test from "node:test";
import { ReplayV2ApiClient, ReplayV2ApiError } from "../replayV2Api.js";
import type { PreparationJob } from "../../data-preparation/api.js";

const identity = { exchange: "binance", marketType: "spot", symbol: "DOGEUSDT" };
const planned = {
  schema_version: "replay.market-track-plan.v1", plan_id: "track-plan-ready", run_id: "run-1",
  identity: { exchange: "binance", market_type: "spot", symbol: "DOGEUSDT", base_asset: "DOGE", settlement_asset: "USDT" },
  subscription_tier: "NONE", compatibility: { state: "READY", code: "MARKET_TRACK_PLAN_READY", message: "ready" },
  expires_at_ms: 1_800_000_000_000,
};
const job = (state: PreparationJob["state"]): PreparationJob => ({
  id: "market-history-1", state, stage: state, completed: state === "READY" ? 1 : 0, total: 1,
  revision: 1, cancel_requested: false,
  request: { consumer: "REPLAY", requirements: [{ symbol: "DOGEUSDT" }], intent: {} },
  result: state === "READY" ? { inputs: [{}] } : null,
  error: state === "FAILED" ? { code: "UPSTREAM_UNAVAILABLE", message: "try again", retryable: true } : null,
});
const failure = (code: string) => Response.json({ protocol: "replay.v3", error: { code, message: code, details: {} } }, { status: 409 });

for (const initial of ["READY", "FAILED", "CANCELLED", "BLOCKED_STORAGE"] as const) {
  test(`second-market acquisition reuses ${initial} job and revalidates admission`, async () => {
    const calls: Array<{ path: string; body: unknown }> = [];
    const progress: string[] = [];
    let plans = 0;
    const client = new ReplayV2ApiClient({ fetcher: async (input, init) => {
      const path = String(input);
      calls.push({ path, body: JSON.parse(String(init?.body ?? "null")) });
      if (path.endsWith("/tracks/plan")) return ++plans === 1 ? failure("MARKET_TRACK_UNAVAILABLE") : Response.json(planned);
      if (path.endsWith("/replay-market")) return Response.json(job(initial), { status: 202 });
      if (path.endsWith("/retry")) return Response.json(job("READY"));
      throw new Error(`unexpected call ${path}`);
    } });
    const result = await client.planMarketTrack("run-1", identity, undefined, (value) => progress.push(value.state));
    assert.equal(result.plan_id, "track-plan-ready");
    assert.equal(plans, 2);
    assert.deepEqual(calls[1], { path: "/api/v1/data-preparations/replay-market", body: {
      run_id: "run-1", exchange: "binance", market_type: "spot", symbol: "DOGEUSDT",
    } });
    assert.equal(calls.filter((call) => call.path.endsWith("/retry")).length, initial === "READY" ? 0 : 1);
    assert.deepEqual(progress, ["READY"]);
    assert.ok(!calls.some((call) => call.path.endsWith("/commands")));
  });
}

test("a scope rejection never starts history acquisition", async () => {
  const calls: string[] = [];
  const client = new ReplayV2ApiClient({ fetcher: async (input) => {
    calls.push(String(input)); return failure("MARKET_SCOPE_MISMATCH");
  } });
  await assert.rejects(client.planMarketTrack("run-1", identity, undefined, () => undefined),
    (error) => error instanceof ReplayV2ApiError && error.code === "MARKET_SCOPE_MISMATCH");
  assert.deepEqual(calls, ["/api/v1/replay/runs/run-1/tracks/plan"]);
});

test("published history still cannot bypass a rejected authoritative plan", async () => {
  const calls: string[] = [];
  const client = new ReplayV2ApiClient({ fetcher: async (input) => {
    const path = String(input); calls.push(path);
    return path.endsWith("/replay-market") ? Response.json(job("READY")) : failure("MARKET_COVERAGE_INSUFFICIENT");
  } });
  await assert.rejects(client.planMarketTrack("run-1", identity, undefined, () => undefined),
    (error) => error instanceof ReplayV2ApiError && error.code === "MARKET_COVERAGE_INSUFFICIENT");
  assert.equal(calls.length, 3);
});

test("leaving preparation stops observation without cancelling durable history", async () => {
  const calls: string[] = [];
  const observer = new AbortController();
  const client = new ReplayV2ApiClient({ fetcher: async (input) => {
    const path = String(input); calls.push(path);
    return path.endsWith("/replay-market") ? Response.json(job("QUEUED")) : failure("MARKET_TRACK_UNAVAILABLE");
  } });
  await assert.rejects(client.planMarketTrack("run-1", identity, observer.signal, () => observer.abort()),
    (error) => error instanceof DOMException && error.name === "AbortError");
  assert.equal(calls.length, 2);
  assert.ok(!calls.some((path) => path.endsWith("/cancel") || path.endsWith("/commands")));
});
