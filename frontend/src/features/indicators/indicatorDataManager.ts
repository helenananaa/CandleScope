import { computeIndicatorBatch, computeIndicatorRangeBatch } from "../../services/indicatorApi.js";
import { buildSeriesWindowKey } from "../market-data/window/seriesWindowKey.js";
import type { MarketSeries, KlineBar } from "../market-data/marketDataTypes.js";
import type { SharedMarketCache } from "../market-data/manager/sharedMarketCache.js";
import type { ForegroundPreloadGate } from "../market-data/foregroundPreloadGate.js";
import { klineSeriesIdentityKey } from "../market-data/klineSeriesIdentity.js";
import { routeIndicatorComputeBatch } from "./frontendScriptBatch.js";
import { awaitIndicatorComputations } from "./indicatorComputeSettlement.js";
import type { IndicatorComputeBatchExecutor } from "./indicatorComputeController.js";
import { createIndicatorCacheInputSource } from "./indicatorInputBinding.js";
import { IndicatorInputRanges } from "./indicatorInputRanges.js";
import { IndicatorRequestBroker, indicatorRequestKey } from "./indicatorRequestBroker.js";
import type { IndicatorComputeRequest, IndicatorPayloadEnvelope, IndicatorRangeRequest, IndicatorRangeBatchResponse } from "./indicatorTypes.js";
import type { SharedIndicatorStreamCoordinator } from "./sharedIndicatorStreamCoordinator.js";

export interface IndicatorDataManagerOptions {
  cache: SharedMarketCache;
  gate: ForegroundPreloadGate;
  streams?: SharedIndicatorStreamCoordinator | null;
  compute?: IndicatorComputeBatchExecutor;
  range?: (options: { requests: IndicatorRangeRequest[]; signal: AbortSignal }) => Promise<IndicatorRangeBatchResponse>;
  coalesceMs?: number;
}

/** One workspace entrance for live indicator IO. The transport does not inherit
 * a chart's request scope, generation, client IDs or cancellation controller. */
export class IndicatorDataManager {
  readonly inputSource;
  readonly inputs: IndicatorInputRanges;
  readonly streams: SharedIndicatorStreamCoordinator | null;
  private readonly scope = `indicator-flow:${crypto.randomUUID()}`;
  private nextRequest = 0;
  private readonly ranges: IndicatorRequestBroker<IndicatorRangeRequest, IndicatorPayloadEnvelope>;
  private readonly computes: IndicatorRequestBroker<IndicatorComputeRequest, IndicatorPayloadEnvelope>;

  constructor(readonly options: IndicatorDataManagerOptions) {
    this.inputSource = createIndicatorCacheInputSource(options.cache);
    this.inputs = new IndicatorInputRanges(options.cache);
    this.streams = options.streams ?? null;
    this.ranges = new IndicatorRequestBroker({
      ...(options.coalesceMs === undefined ? {} : { coalesceMs: options.coalesceMs }),
      send: async (requests, signal) => {
        const physical = requests.map(request => ({ ...request, clientId: this.id(),
          requestScope: this.scope, requestGeneration: 1 }));
        const response = await (options.range ?? computeIndicatorRangeBatch)({ requests: physical, signal });
        if (response.results.length !== physical.length || response.results.some((item, index) => item.clientId !== physical[index]!.clientId)) {
          throw new Error("Indicator range response identity mismatch");
        }
        return response.results.map(item => item.payload);
      },
    });
    this.computes = new IndicatorRequestBroker({
      ...(options.coalesceMs === undefined ? {} : { coalesceMs: options.coalesceMs }),
      send: async (requests, signal, publish) => {
        // The broker's group proves exact OHLCV equality; the wire API also
        // requires all jobs to reference the same owned input array.
        const ohlcv = requests[0]!.ohlcv;
        const jobs = requests.map(request => { const id = this.id(); return { clientId: id, jobKey: id, request: { ...request, ohlcv } }; });
        const indexes = new Map(jobs.map((job, index) => [job.jobKey, index]));
        const response = await (options.compute ?? (input => routeIndicatorComputeBatch(input, computeIndicatorBatch)))({
          jobs, signal, onResults: results => {
            for (const item of results) {
              const index = indexes.get(item.jobKey);
              if (index === undefined || item.clientId !== jobs[index]!.clientId) throw new Error("Indicator compute response identity mismatch");
              publish(index, item.payload);
            }
          },
        });
        const results = new Map(response.results.map(item => [item.jobKey, item]));
        if (response.results.length !== jobs.length || results.size !== jobs.length
          || jobs.some(job => results.get(job.jobKey)?.clientId !== job.clientId)) throw new Error("Indicator compute response identity mismatch");
        return jobs.map(job => results.get(job.jobKey)!.payload);
      },
    });
  }

  range = (request: IndicatorRangeRequest, speculative = false): Promise<IndicatorPayloadEnvelope> => {
    const series = this.series(request);
    const closed = this.options.cache.read(series, { finalOnly: true }).rows.at(-1);
    const version = this.inputSource.capture(series, Math.min(request.end, Number(closed?.time ?? request.end)));
    const { clientId: _clientId, customId: _customId, signal, requestScope: _scope,
      requestGeneration: _generation, reason: _reason, ...semantic } = request;
    void _clientId; void _customId; void _scope; void _generation; void _reason;
    const promise = this.ranges.request({
      key: indicatorRequestKey({ ...semantic, ...(!request.script?.trim() && request.customId ? { customId: request.customId } : {}),
        seriesIdentity: klineSeriesIdentityKey(series.exchange, series) }),
      group: String(buildSeriesWindowKey(series)), request: { ...semantic, clientId: "pending",
        ...(request.customId === undefined ? {} : { customId: request.customId }) },
      signal, speculative, current: () => version.isCurrent(),
    });
    return this.foreground(promise, speculative);
  };

  compute: IndicatorComputeBatchExecutor = options => this.computeDemand(options);

  computeDemand(options: Parameters<IndicatorComputeBatchExecutor>[0], speculative = false): ReturnType<IndicatorComputeBatchExecutor> {
    const results = options.jobs.map(job => {
      const request = job.request, series = this.series(request);
      const current = this.computeInputCurrent(series, request.ohlcv as KlineBar[]);
      const group = indicatorRequestKey({ series: String(buildSeriesWindowKey(series)), ohlcv: request.ohlcv, replayContext: request.replayContext });
      return this.computes.request({
        key: indicatorRequestKey({ ...request, seriesIdentity: klineSeriesIdentityKey(series.exchange, series) }),
        group, request, signal: options.signal, speculative,
        current,
      }).then(payload => {
        const result = { clientId: job.clientId, jobKey: job.jobKey, payload };
        options.onResults?.([result]); return result;
      });
    });
    return this.foreground(awaitIndicatorComputations(results).then(results => ({ ok: true, results })), speculative);
  }

  diagnostics() { return { range: this.ranges.diagnostics(), compute: this.computes.diagnostics(), inputs: this.inputs.diagnostics() }; }
  dispose(): void { this.ranges.dispose(); this.computes.dispose(); this.inputs.dispose(); }
  private id(): string { return `${this.scope}:${++this.nextRequest}`; }
  private computeInputCurrent(series: MarketSeries, rows: KlineBar[]): () => boolean {
    const last = rows.at(-1);
    if (last?.is_closed !== false) {
      const version = this.inputSource.captureProvided(series, rows);
      return () => version?.isCurrent() === true;
    }
    // Live JS intentionally holds one forming sample while it computes. Tick
    // updates may not starve that preview; closed input, finality, corrections
    // and disconnects remain strict. The result cache separately requires an
    // exact full-input stamp and never certifies a superseded forming sample.
    const closed = rows.slice(0, -1);
    const version = closed.length ? this.inputSource.captureProvided(series, closed)
      : this.inputSource.capture(series, Number(last.time) - 1, Number(last.time));
    return () => version?.isCurrent() === true
      && this.options.cache.read(series, { from: Number(last.time), to: Number(last.time) }).rows[0]?.is_closed === false;
  }
  private series(request: Pick<IndicatorComputeRequest, "exchange" | "marketType" | "symbol" | "interval" | "seriesIdentity">): MarketSeries {
    return { ...request.seriesIdentity, exchange: request.exchange || "binance", marketType: request.marketType || "spot",
      symbol: request.symbol || "", interval: request.interval || "" };
  }
  private foreground<T>(promise: Promise<T>, speculative: boolean): Promise<T> {
    if (speculative) return promise;
    // Join first: preempting the warm consumer cannot cancel this demand.
    const lease = this.options.gate.enterForeground(this.id());
    return promise.finally(() => lease.release());
  }
}
