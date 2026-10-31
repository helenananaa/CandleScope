import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { ChartDataFlowManager, indicatorWarmPlanKey } from "../manager/chartDataFlowManager.js";
import { MarketDataManager } from "../manager/marketDataManager.js";
import { ForegroundPreloadGate } from "../foregroundPreloadGate.js";
import { IndicatorDataManager, type IndicatorDataManagerOptions } from "../../indicators/indicatorDataManager.js";
import { registerSharedMarketCache } from "../../cache-gc/sharedMarketCacheOwner.js";
import { buildIndicatorCacheContext, getCachedIndicatorResult, resetIndicatorResultCache } from "../../indicators/indicatorResultCacheStore.js";
import { buildIndicatorOhlcv, buildIndicatorOhlcvSignature } from "../../indicators/indicatorComputeRuntime.js";
import { cachedIndicatorComputeResult } from "../../indicators/indicatorCachedCompute.js";
import { parseIndicatorPayloadEnvelope } from "../../indicators/indicatorContracts.js";
import type { KlineApi } from "../klineContracts.js";
import type { EpochSeconds, MarketSeries } from "../marketDataTypes.js";
import type { IndicatorDefinition } from "../../indicators/indicatorTypes.js";

const series: MarketSeries = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const now = 1_800_000_000_000;
const rows = Array.from({ length: 500 }, (_, i) => ({ time: ((i + 1) * 60) as EpochSeconds, open: 10, high: 20, low: 5, close: 12, volume: 1, is_closed: true }));
const payload = parseIndicatorPayloadEnvelope({ ok: true, lines: [{ id: "ema", data: [{ time: 30000, value: 12 }] }] });
const local: IndicatorDefinition = { id: "local", executionTarget: "local", engineName: "EMA", params: { length: 20 } };
const hosted: IndicatorDefinition = { id: "hosted", engineName: "EMA", params: { length: 20 } };
const plan = { indicators: [local, hosted], candleUpColor: "#0f0", candleDownColor: "#f00" };
const tick = () => new Promise<void>(resolve => setTimeout(resolve, 15));
function setup(t: TestContext, options: Partial<IndicatorDataManagerOptions> = {}) {
  resetIndicatorResultCache();
  const gate = new ForegroundPreloadGate(0);
  const market = new MarketDataManager({ api: {} as KlineApi, foregroundPreloadGate: gate, cache: { now: () => now },
    streams: { subscribe: () => { throw new Error("unexpected market IO"); }, closeAll() {}, diagnostics: () => ({}) } });
  // This test isolates indicator intent. The production browser fixture also
  // exercises real market warm orchestration and private chart publication.
  market.warm = () => ({ done: Promise.resolve("warmed"), release() {} });
  market.prepareForeground = () => ({ release() {} });
  const indicators = new IndicatorDataManager({ cache: market.cache, gate, coalesceMs: 0,
    compute: async ({ jobs }) => ({ ok: true, results: jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) }),
    range: async ({ requests }) => ({ ok: true, results: requests.map(request => ({ clientId: request.clientId, payload })) }), ...options });
  const flow = new ChartDataFlowManager(market, indicators, () => now);
  t.after(() => { flow.dispose(); market.closeAll(); gate.dispose(); });
  t.after(registerSharedMarketCache(market.cache));
  const wire = (sequence: number) => ({ protocol: 1, epoch: "test", generation: 1, sequence, barrier: sequence, observed_at_ms: now, stable: true,
    series: { exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "1m", provider_id: "binance", venue: "binance",
      asset_class: "crypto", series_variant: "native", price_adjustment: "raw", session_variant: "continuous", volume_semantics: "base_asset" } });
  market.cache.connect(series);
  const token = market.cache.beginRead(series);
  market.cache.admitResponse(token, { data: rows, stream_version: wire(0), all_rows_final: true, complete: true, retryable: false,
    history_state: "ready", verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false }); token.release();
  market.cache.admitRealtime(series, { ...rows.at(-1)!, time: 30060 as EpochSeconds, is_closed: false }, "bar.created", wire(1), 30000_000);
  assert.equal(market.cache.planHistory(series, 500).action, "reuse");
  const provided = [...market.cache.read(series, { limit: 2000 }).rows];
  const context = buildIndicatorCacheContext({ ...series, seriesIdentity: series, inputSource: indicators.inputSource,
    localInputKey: buildIndicatorOhlcvSignature(provided), candleUpColor: plan.candleUpColor, candleDownColor: plan.candleDownColor });
  flow.registerPlan("a", plan);
  const chart = flow.forChart("a");
  const warm = () => chart.warm(series, { owner: "hover-a", reason: "hover", nativeIntervals: ["1m"] });
  return { flow, market, indicators, gate, chart, warm, provided, context };
}

test("healthy target warms both execution routes; exact cached computation bypasses execution", async t => {
  const { warm, flow, market, context, provided } = setup(t);
  warm(); await tick();
  assert.equal(flow.diagnostics().warmed, 2);
  const job = { clientId: local.id, jobKey: "current", request: { ...series, mode: "builtin", name: "EMA", ohlcv: buildIndicatorOhlcv(provided), params: local.params ?? {} } };
  assert.equal(cachedIndicatorComputeResult(job, local, context, false)?.payload.lines.length, 1);
  assert.equal(cachedIndicatorComputeResult(job, local, context, true), null, "force recomputes");
  assert.equal(cachedIndicatorComputeResult(job, local, null, false), null, "replay has no shared cache");
  assert.equal(cachedIndicatorComputeResult({ ...job, request: { ...job.request, ohlcv: buildIndicatorOhlcv(provided.slice(1)) } }, local, context, false), null);
  assert.deepEqual(flow.health(hosted, context, { start: 60, end: 30000 }), {
    covered: true, input: "current", sourceContinuous: true, sourceFresh: true, lastComputedAt: getCachedIndicatorResult(hosted, context)!.lastUpdatedMs,
  });
  market.cache.markDisconnected(series);
  assert.equal(cachedIndicatorComputeResult(job, local, context, false), null);
  assert.equal(flow.health(hosted, context, { start: 60, end: 30000 }).sourceFresh, false);
});

test("promotion transfers warm demand before pointer cancellation and foreground preemption", async t => {
  let finish!: () => void, signal!: AbortSignal, calls = 0;
  const { warm, chart, indicators, context, provided, flow } = setup(t, { compute: async options => {
    calls += 1; signal = options.signal!; await new Promise<void>(resolve => { finish = resolve; });
    return { ok: true, results: options.jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) };
  } });
  const hover = warm(); await tick();
  const handoff = chart.prepareForeground(series); hover.release();
  const foreground = indicators.compute({ jobs: [{ clientId: "local", jobKey: "front", request: {
    ...series, seriesIdentity: series, mode: "builtin", name: "EMA", params: local.params ?? {}, ohlcv: buildIndicatorOhlcv(provided),
  } }] });
  await tick(); assert.equal(signal.aborted, false); assert.equal(calls, 1);
  finish(); await foreground; await tick(); handoff.release();
  assert.ok(getCachedIndicatorResult(local, context)); assert.equal(flow.diagnostics().warming, 0);
});

test("unrelated foreground and plan replacement cancel speculative results", async t => {
  for (const mode of ["foreground", "plan"] as const) {
    let finish!: () => void, signal!: AbortSignal;
    const { warm, gate, flow, context } = setup(t, { compute: async options => {
      signal = options.signal!; await new Promise<void>(resolve => { finish = resolve; });
      return { ok: true, results: options.jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload })) };
    } });
    warm(); await tick();
    const lease = mode === "foreground" ? gate.enterForeground("other-chart") : null;
    if (mode === "plan") flow.registerPlan("a", { ...plan, indicators: [{ ...local, params: { length: 99 } }] });
    assert.equal(signal.aborted, true); finish(); await tick(); lease?.release();
    assert.equal(getCachedIndicatorResult(local, context), null);
  }
});

test("unhealthy targets never compute; targets and enabled definitions have fixed budgets", async t => {
  const { flow, market, chart } = setup(t);
  market.cache.markDisconnected(series);
  const leases = Array.from({ length: 8 }, (_, i) => chart.warm({ ...series, symbol: `COIN${i}` }, { owner: "a", reason: "hover", nativeIntervals: ["1m"] }));
  await tick(); assert.equal(flow.diagnostics().warming, 4); assert.equal(flow.diagnostics().rejected, 4);
  assert.equal(flow.diagnostics().indicators.compute.totalPhysical, 0);
  leases.forEach(lease => lease.release()); assert.equal(flow.diagnostics().warming, 0);
  const parsed = JSON.parse(indicatorWarmPlanKey({ ...plan, indicators: [
    { ...local, id: "hidden", visible: false }, { ...local, id: "error", error: "broken" },
    { id: "retired", language: "pyne", script: "old script" },
    ...Array.from({ length: 12 }, (_, i) => ({ ...local, id: `ok-${i}`, lines: [] })),
  ] })) as { indicators: IndicatorDefinition[] };
  const definitions = parsed.indicators;
  assert.equal(definitions.length, 8); assert.ok(definitions.every(item => item.id.startsWith("ok-")));
  assert.equal(indicatorWarmPlanKey(plan), indicatorWarmPlanKey({ ...plan, indicators: plan.indicators.map(item => ({ ...item, lines: [] })) }));
});
