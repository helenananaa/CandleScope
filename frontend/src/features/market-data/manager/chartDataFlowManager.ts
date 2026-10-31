import type { MarketDataManager } from "./marketDataManager.js";
import type { MarketDataService } from "../marketDataService.js";
import type { MarketSeries } from "../marketDataTypes.js";
import type { PreloadLease } from "../foregroundPreloadGate.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";
import type { IndicatorDataManager } from "../../indicators/indicatorDataManager.js";
import type { IndicatorCacheContext, IndicatorDefinition, IndicatorRange } from "../../indicators/indicatorTypes.js";
import { buildIndicatorComputeParams, buildIndicatorOhlcv, buildIndicatorOhlcvSignature } from "../../indicators/indicatorComputeRuntime.js";
import { resolveLocalIndicatorExecution } from "../../indicators/indicatorComputeJobRuntime.js";
import { buildHostedSubscriptionMessage } from "../../indicators/indicatorWsRuntime.js";
import { normalizeParsedIndicatorPayload } from "../../indicators/indicatorPayloadRuntime.js";
import { buildIndicatorCacheContext, cacheIndicatorSnapshot, getCachedIndicatorResult, replaceCachedIndicatorRange } from "../../indicators/indicatorResultCacheStore.js";
import { indicatorRangeCovered, normalizeIndicatorRange, normalizeIndicatorRevision } from "../../indicators/indicatorRangeCoverage.js";
import { indicatorRequestKey } from "../../indicators/indicatorRequestBroker.js";

export interface IndicatorWarmPlan { indicators: IndicatorDefinition[]; candleUpColor: string; candleDownColor: string }

/** Output ticks must not replace a chart's declaration of computation intent. */
export function indicatorWarmPlanKey(plan: IndicatorWarmPlan): string {
  return indicatorRequestKey({ ...plan, indicators: plan.indicators.filter(indicator => indicator.visible !== false
    && !indicator.error && String(indicator.language || "").trim().toLowerCase() !== "pyne"
    && resolveLocalIndicatorExecution(indicator).kind !== "invalid").slice(0, 8).map(indicator => ({
      id: indicator.id, name: indicator.name, engineName: indicator.engineName, kind: indicator.kind,
      is_builtin: indicator.is_builtin, script: indicator.script, language: indicator.language,
      executionTarget: indicator.executionTarget, securityMode: indicator.securityMode, params: indicator.params,
    })) });
}

interface WarmJob {
  key: string;
  owner: string;
  series: MarketSeries;
  plan: IndicatorWarmPlan;
  controller: AbortController;
  lease: PreloadLease | null;
  cleanup(): void;
  timer: ReturnType<typeof setTimeout>;
  holds: number;
  consumers: number;
  started: boolean;
}

/** Coordinates selection intent only; market admission, indicator execution and
 * chart windows retain their existing owners. Warming never publishes to a chart. */
export class ChartDataFlowManager {
  private readonly plans = new Map<string, IndicatorWarmPlan>();
  private readonly warming = new Map<string, WarmJob>();
  private attempts: number[] = [];
  private readonly unsubscribe: () => void;
  private pumping = false;
  private disposed = false;
  private warmed = 0;
  private rejected = 0;
  constructor(readonly market: MarketDataManager, readonly indicators: IndicatorDataManager, private readonly now = Date.now) {
    this.unsubscribe = market.foregroundPreloadGate.subscribe(() => this.pump());
  }

  registerPlan(owner: string, plan: IndicatorWarmPlan): () => void {
    const frozenPlan = JSON.parse(indicatorWarmPlanKey(plan)) as IndicatorWarmPlan;
    this.plans.set(owner, frozenPlan);
    for (const job of [...this.warming.values()]) if (job.owner === owner) this.finish(job);
    return () => {
      if (this.plans.get(owner) !== frozenPlan) return;
      this.plans.delete(owner);
      for (const job of [...this.warming.values()]) if (job.owner === owner) this.finish(job);
    };
  }

  forChart(owner: string): Pick<MarketDataService, "warm" | "prepareForeground"> {
    return {
      warm: (series, options) => {
        const market = this.market.warm(series, options);
        const releaseIndicators = this.warm(owner, series);
        return { done: market.done, release: () => { market.release(); releaseIndicators(); } };
      },
      prepareForeground: series => {
        const market = this.market.prepareForeground(series);
        const jobs = [...this.warming.values()].filter(job => job.owner === owner && job.started
          && String(buildSeriesWindowKey(job.series)) === String(buildSeriesWindowKey(series)));
        for (const job of jobs) {
          job.holds += 1;
          if (job.lease) this.market.foregroundPreloadGate.release(job.lease);
          job.lease = null;
        }
        let released = false;
        return { release: () => {
          if (released) return; released = true; market.release();
          for (const job of jobs) { job.holds -= 1; this.releaseUnused(job); }
        } };
      },
    };
  }

  health(indicator: IndicatorDefinition, context: IndicatorCacheContext, range: IndicatorRange) {
    const result = getCachedIndicatorResult(indicator, context);
    const series = { ...context.seriesIdentity, ...context };
    const source = this.market.cache.planHistory(series, 1).health;
    return {
      covered: Boolean(result && indicatorRangeCovered(range, result.computedSegments, { interval: context.interval })),
      input: result ? "current" : "missing-or-invalid",
      sourceContinuous: source.continuous,
      sourceFresh: source.fresh,
      lastComputedAt: result?.lastUpdatedMs ?? null,
    };
  }

  diagnostics() { return { plans: this.plans.size, warming: this.warming.size, warmed: this.warmed, rejected: this.rejected, indicators: this.indicators.diagnostics() }; }
  dispose(): void {
    this.disposed = true; this.unsubscribe(); this.plans.clear();
    for (const job of [...this.warming.values()]) this.finish(job);
    this.indicators.dispose();
  }

  private warm(owner: string, series: MarketSeries): () => void {
    const plan = this.plans.get(owner);
    if (this.disposed || !plan?.indicators.length) return () => {};
    const key = `${owner}|${buildSeriesWindowKey(series)}`;
    let job = this.warming.get(key);
    if (!job) {
      this.attempts = this.attempts.filter(at => at + 30_000 > this.now());
      // Four targets, eight indicators each, one attempt per intent; no retry loop.
      if (this.attempts.length >= 4 || this.warming.size >= 4) { this.rejected += 1; return () => {}; }
      this.attempts.push(this.now());
      const controller = new AbortController();
      job = { key, owner, series: { ...series }, plan, controller, lease: null, cleanup() {}, holds: 0,
        consumers: 0, started: false, timer: setTimeout(() => { if (job) this.finish(job); }, 30_000) };
      job.cleanup = this.market.cache.subscribe(series, () => this.pump());
      this.warming.set(key, job);
    }
    const target = job;
    target.consumers += 1; this.pump();
    let released = false;
    return () => { if (released) return; released = true; target.consumers -= 1; this.releaseUnused(target); };
  }

  private pump(): void {
    if (this.disposed || this.pumping) return;
    this.pumping = true;
    try {
      for (const job of this.warming.values()) {
        if (job.started || this.market.cache.planHistory(job.series, 500).action !== "reuse") continue;
        const lease = this.market.foregroundPreloadGate.tryAcquireIntentPreload(`indicator-warm:${job.key}`);
        if (!lease) continue;
        job.lease = lease; job.started = true;
        const abort = () => this.finish(job);
        lease.controller.signal.addEventListener("abort", abort, { once: true });
        void this.run(job).catch(() => { /* Speculation must never fail the chart selection. */ })
          .finally(() => { lease.controller.signal.removeEventListener("abort", abort); this.finish(job); });
      }
    } finally { this.pumping = false; }
  }

  private async run(job: WarmJob): Promise<void> {
    const rows = [...this.market.cache.read(job.series, { limit: 2000 }).rows];
    const closed = this.market.cache.read(job.series, { limit: 500, finalOnly: true }).rows;
    const range = { start: Number(closed[0]!.time), end: Number(closed.at(-1)!.time) };
    const context = buildIndicatorCacheContext({ ...job.series, seriesIdentity: job.series,
      inputSource: this.indicators.inputSource, localInputKey: buildIndicatorOhlcvSignature(rows),
      candleUpColor: job.plan.candleUpColor, candleDownColor: job.plan.candleDownColor });
    await Promise.all(job.plan.indicators.map(async indicator => {
      const resolution = resolveLocalIndicatorExecution(indicator);
      const cached = getCachedIndicatorResult(indicator, context);
      if (cached && (resolution.kind === "local" || indicatorRangeCovered(range, cached.computedSegments, { interval: job.series.interval }))) return;
      const inputVersion = resolution.kind === "local" ? this.indicators.inputSource.captureProvided(job.series, rows)
        : this.indicators.inputSource.capture(job.series, range.end);
      if (!inputVersion?.isCurrent()) return;
      let payload;
      if (resolution.kind === "local") {
        const response = await this.indicators.computeDemand({ signal: job.controller.signal, jobs: [{
          clientId: indicator.id, jobKey: indicator.id,
          request: { ...resolution.execution, ...job.series, seriesIdentity: job.series,
            ...(indicator.language === undefined ? {} : { language: indicator.language }),
            params: buildIndicatorComputeParams(indicator, job.plan), ohlcv: buildIndicatorOhlcv(rows) },
        }] }, true);
        payload = response.results[0]!.payload;
      } else if (resolution.kind === "hosted") {
        const message = buildHostedSubscriptionMessage(indicator, { ...context, chartDataLength: closed.length });
        payload = await this.indicators.range({ ...message, ...range, start: range.start, end: range.end,
          signal: job.controller.signal, reason: "prewarm" }, true);
      } else return;
      if (payload.ok === false || job.controller.signal.aborted || !inputVersion.isCurrent() || this.plans.get(job.owner) !== job.plan) return;
      const normalized = normalizeParsedIndicatorPayload(payload, indicator.id);
      if (resolution.kind === "hosted") {
        // A successful backend read may cover less than the request. Retain
        // that exact proof/revision and preserve valid output outside it.
        const returned = normalizeIndicatorRange(payload.range) ?? range;
        const covered = normalizeIndicatorRange({ start: Math.max(range.start, returned.start), end: Math.min(range.end, returned.end) });
        if (!covered) return;
        const revision = normalizeIndicatorRevision(payload);
        const stored = getCachedIndicatorResult(indicator, context)
          ? replaceCachedIndicatorRange(indicator, context, normalized, covered, { revision })
          : cacheIndicatorSnapshot(indicator, context, normalized, payload.param_schema, { inputVersion, range: covered, revision });
        if (stored) this.warmed += 1;
      } else if (cacheIndicatorSnapshot(indicator, context, normalized, payload.param_schema,
        { inputVersion, range: { start: Number(rows[0]!.time), end: Number(rows.at(-1)!.time) } })) this.warmed += 1;
    }));
  }

  private releaseUnused(job: WarmJob): void { if (!job.consumers && !job.holds) this.finish(job); }
  private finish(job: WarmJob): void {
    if (this.warming.get(job.key) !== job) return;
    this.warming.delete(job.key); clearTimeout(job.timer); job.cleanup(); job.controller.abort();
    this.market.foregroundPreloadGate.cancelQueued(`indicator-warm:${job.key}`);
    if (job.lease) this.market.foregroundPreloadGate.release(job.lease);
  }
}
