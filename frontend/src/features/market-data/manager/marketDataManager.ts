import type {
  KlineApi, KlineFetchResult, KlineHistoryBatchOutcome, KlineRequestOptions, KlineStreamFactory,
} from "../klineContracts.js";
import type { MarketSeries } from "../marketDataTypes.js";
import { SharedKlineRequestCoordinator } from "../feed/sharedKlineRequestCoordinator.js";
import { SharedKlineStreamCoordinator } from "../feed/sharedKlineStreamCoordinator.js";
import { SharedMarketCache, type MarketCacheOptions, type MarketReadToken } from "./sharedMarketCache.js";
import type { MarketRange } from "./sharedMarketCache.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { MarketDataService, MarketWarmOptions } from "../marketDataService.js";
import { ForegroundPreloadGate } from "../foregroundPreloadGate.js";
import { planTargetBarRequest } from "../intervalRequestBudget.js";
import { MarketHealthRecovery } from "./marketHealthRecovery.js";
import { MarketWarmStreams } from "./marketWarmStreams.js";
import { MarketWarmQueue, type MarketWarmLease } from "./marketWarmQueue.js";
import { MarketDataManagerCore } from "./marketDataManagerCore.js";

interface StreamTransport {
  readonly reconnects?: boolean;
  subscribe: KlineStreamFactory;
  closeAll(): void;
  diagnostics(): object;
}
export interface MarketDataManagerOptions {
  api: KlineApi;
  streams: StreamTransport;
  batchHistory?: boolean;
  cache?: MarketCacheOptions;
  warmStreams?: { maxSeries?: number; ttlMs?: number };
  foregroundPreloadGate?: ForegroundPreloadGate;
}

function identity(symbol: string, interval: string, marketType: string, exchange: string, options: KlineRequestOptions): MarketSeries {
  return { ...options.seriesIdentity, symbol, interval, marketType, exchange };
}

function aborted(): DOMException { return new DOMException("The operation was aborted", "AbortError"); }

/** Frontend workspace data boundary. Physical responses are admitted once before
 * fan-out. Chart/watchlist consumers own independent request/stream leases;
 * cache facts contain no viewport or chart-selection state. */
export class MarketDataManager extends MarketDataManagerCore implements MarketDataService {
  readonly ownsRequestLeases = true;
  readonly cache: SharedMarketCache;
  readonly requestCoordinator: SharedKlineRequestCoordinator;
  readonly foregroundPreloadGate: ForegroundPreloadGate;
  readonly warmQueue: MarketWarmQueue;
  private readonly sharedStreams: SharedKlineStreamCoordinator;
  private readonly transport: StreamTransport;
  private readonly api: KlineApi;
  private readonly warmStreams: MarketWarmStreams;
  private readonly healthRecovery: MarketHealthRecovery;
  private readonly ownsForegroundGate: boolean;
  private closed = false;
  private rejectedRealtime = 0;
  private rangeHits = 0;
  private beforeHits = 0;
  private historyHits = 0;

  constructor(options: MarketDataManagerOptions) {
    super();
    this.api = options.api;
    this.transport = options.streams;
    this.cache = new SharedMarketCache(options.cache);
    const api = options.api;
    const admittedApi: KlineApi = {
      getMultiStreamUrl: (...args) => api.getMultiStreamUrl(...args),
      fetchKlinesHistory: (...args) => this.acceptHttp(identity(args[0], args[1], args[3], args[4], args[5]), args[5], "history", () => api.fetchKlinesHistory(...args)),
      fetchKlinesBefore: (...args) => this.acceptHttp(identity(args[0], args[1], args[4], args[5], args[6]), args[6], "before", () => api.fetchKlinesBefore(...args)),
      fetchKlinesRange: (...args) => this.acceptHttp(identity(args[0], args[1], args[4], args[5], args[6]), args[6], "range", () => api.fetchKlinesRange(...args)),
      fetchLatestKlines: (...args) => this.acceptHttp(identity(args[0], args[1], args[3], args[4], args[6]), args[6], "latest", () => api.fetchLatestKlines(...args)),
    };
    if (api.fetchKlinesHistoryBatch) {
      admittedApi.fetchKlinesHistoryBatch = async (requests, requestOptions) => {
        const tokens: MarketReadToken[] = [];
        try {
          for (const request of requests) tokens.push(this.cache.beginRead(identity(request.symbol, request.interval, request.marketType, request.exchange, request.options)));
          const outcomes = await api.fetchKlinesHistoryBatch!(requests, requestOptions);
          if (this.closed || requestOptions.signal?.aborted) throw aborted();
          return requests.map((_, index): KlineHistoryBatchOutcome => {
            const outcome = outcomes[index];
            if (!outcome) return { ok: false, error: new Error("Missing history batch outcome") };
            if (!outcome.ok) return outcome;
            try { return { ok: true, result: this.cache.admitResponse(tokens[index]!, { ...outcome.result, endpoint: "history" }) }; }
            catch (error) { return { ok: false, error: error instanceof Error ? error : new Error(String(error)) }; }
          });
        } finally { tokens.forEach(token => token.release()); }
      };
    }
    this.requestCoordinator = new SharedKlineRequestCoordinator(admittedApi, options.batchHistory ?? true);
    this.foregroundPreloadGate = options.foregroundPreloadGate ?? new ForegroundPreloadGate();
    this.ownsForegroundGate = !options.foregroundPreloadGate;
    this.warmQueue = new MarketWarmQueue({ gate: this.foregroundPreloadGate,
      read: (request, signal) => this.requestCoordinator.fetchKlinesHistory(request.series.symbol, request.series.interval,
        null, request.series.marketType, request.series.exchange, {
          countBack: request.limit, maxWaitMs: 0, intent: "viewport", seriesIdentity: request.series,
          signal, clientContext: { priority: 2, cacheMode: "network-only" },
        }),
    });
    this.sharedStreams = new SharedKlineStreamCoordinator(api, {
      reconnects: this.transport.reconnects ?? false,
      createPhysicalStream: (series, streamOptions) => {
        // Transport socket epochs are fenced by the transport. Lease disposal
        // is terminal, while a reconnecting transport may reopen this lease.
        let active = true;
        let connected = true;
        let intervals = [...(streamOptions.intervals ?? [])];
        const connect = () => { for (const interval of intervals) this.cache.connect({ ...series, interval }); };
        const current = () => active && !this.closed;
        const controller = this.transport.subscribe(series, {
        ...streamOptions,
        onOpen: controller => { if (current()) { connected = true; connect(); streamOptions.onOpen?.(controller); } },
        onStreamStatus: (event, controller) => {
          if (!current()) return;
          if (event.status !== "online" && event.status !== "connected") this.cache.markDisconnected(series);
          streamOptions.onStreamStatus?.(event, controller);
        },
        onControlMessage: (event, controller) => {
          if (!current() || !connected) return;
          for (const failure of event.failed ?? []) this.cache.disconnectSeries({ ...series, interval: failure.interval });
          if (event.type === "unsubscribed") for (const interval of event.intervals ?? event.requested_intervals ?? []) {
            this.cache.disconnectSeries({ ...series, interval });
          }
          if (event.type === "subscribed" && event.active_intervals) for (const interval of intervals) {
            if (!event.active_intervals.includes(interval)) this.cache.disconnectSeries({ ...series, interval });
          }
          if (event.type === "error") this.cache.markDisconnected(series);
          streamOptions.onControlMessage?.(event, controller);
        },
        onBackfillCompleted: (event, controller) => {
          if (!current() || !connected) return false;
          // A new backend completion is not validated by an earlier cache proof.
          const from = event.detail?.range_start_ms ?? event.detail?.request_start_ms;
          const to = event.detail?.range_end_ms ?? event.detail?.request_end_ms;
          if (event.interval) this.cache.invalidateRange({ ...series, interval: event.interval },
            typeof from === "number" && typeof to === "number" && Number.isFinite(from) && Number.isFinite(to) && from <= to
              ? { from: from / 1000, to: to / 1000 } : undefined, event.stream_version);
          else this.cache.markDisconnected(series);
          if (event.interval) this.healthRecovery.request({ ...series, interval: event.interval });
          return streamOptions.onBackfillCompleted?.(event, controller) ?? false;
        },
        onParseError: (error, event, controller) => {
          if (!current()) return;
          this.cache.markDisconnected(series);
          streamOptions.onParseError?.(error, event, controller);
        },
        onKline: (event, controller) => {
          if (!current() || !connected) return;
          this.cache.connect({ ...series, interval: event.interval });
          const accepted = this.cache.admitRealtime({ ...series, interval: event.interval }, event.tick,
            typeof event.message.event_type === "string" ? event.message.event_type : undefined,
            event.message.stream_version, event.message.previous_open_ms);
          this.healthRecovery.request({ ...series, interval: event.interval });
          if (!accepted.accepted || !accepted.row) { this.rejectedRealtime += 1; return; }
          streamOptions.onKline?.({ ...event, tick: accepted.row, message: { ...event.message, data: accepted.row } }, controller);
        },
        onError: (event, controller) => {
          if (!current()) return;
          this.cache.markDisconnected(series);
          streamOptions.onError?.(event, controller);
        },
        onClose: (event, controller) => {
          if (!current()) return;
          connected = false;
          if (!this.transport.reconnects) active = false;
          this.cache.markDisconnected(series);
          streamOptions.onClose?.(event, controller);
        },
        });
        return {
          readyState: () => controller.readyState(), isOpen: () => current() && controller.isOpen(),
          send: payload => current() && controller.send(payload), sendPing: () => current() && controller.sendPing(),
          updateIntervals: next => {
            if (!current()) return;
            for (const interval of intervals) if (!next.includes(interval)) this.cache.disconnectSeries({ ...series, interval });
            intervals = [...next];
            if (controller.isOpen()) connect();
            controller.updateIntervals(next);
          },
          close: () => {
            active = false;
            // Releasing the last stream lease must not cancel another
            // consumer's independent HTTP lease. It only revokes live health.
            this.cache.markDisconnected(series, false); controller.close();
          },
        };
      },
    });
    this.healthRecovery = new MarketHealthRecovery(series => this.cache.verificationDemand(series),
      (series, limit, signal) => this.requestCoordinator.fetchKlinesHistory(series.symbol, series.interval, null,
        series.marketType, series.exchange, { countBack: limit, maxWaitMs: 0, intent: "viewport", seriesIdentity: series,
          signal, clientContext: { cacheMode: "network-only", priority: 1 } }));
    this.warmStreams = new MarketWarmStreams(this.subscribe, options.warmStreams?.maxSeries, options.warmStreams?.ttlMs);
  }

  readonly subscribe: KlineStreamFactory = (series, options) => {
    if (this.closed) throw new Error("MarketDataManager is closed");
    return this.sharedStreams.subscribe(series, options);
  };

  readonly fetchKlinesHistory: KlineApi["fetchKlinesHistory"] = (...args) => {
    const options = args[5];
    if (this.closed || options.signal?.aborted) return Promise.reject(aborted());
    if (options.clientContext?.cacheMode === "prefer-cache" && options.countBack
      && (options.intent === "viewport" || options.intent === "active_hydration")) {
      const decision = this.cache.planHistory(identity(args[0], args[1], args[3], args[4], options), options.countBack);
      if (decision.action === "reuse") {
        this.historyHits += 1;
        return Promise.resolve({ data: [...decision.snapshot.rows], endpoint: "history", source: "healthy-market-cache",
          cacheRevision: decision.snapshot.version, marketHealth: decision.health,
          all_rows_final: true, complete: true, retryable: false, history_state: "ready",
          verified_contiguous: true, missing_ranges: [], has_tail_gap: false, truncated: false,
          reached_latest_closed_bar: true, has_more: true });
      }
    }
    // count_back overrides days at the HTTP boundary. getBars supplies a
    // derived day fallback even for an exact count request; it is not a
    // different input window and must not prevent the production handoff.
    if (options.intent === "viewport" && options.maxWaitMs === 0 && options.countBack) {
      const promoted = this.warmQueue.joinForeground(identity(args[0], args[1], args[3], args[4], options), options.countBack, options.signal);
      if (promoted) return promoted;
    }
    return this.requestCoordinator.fetchKlinesHistory(...args);
  };
  readonly fetchKlinesBefore: KlineApi["fetchKlinesBefore"] = async (...args) => {
    const [symbol, interval, before, bars, marketType, exchange, options] = args;
    if (this.closed || options.signal?.aborted) throw aborted();
    if (before !== undefined && Number.isFinite(before) && options.clientContext?.cacheMode === "prefer-cache") {
      const snapshot = this.cache.read(identity(symbol, interval, marketType, exchange, options), { before, limit: bars });
      if (snapshot.complete) {
        this.beforeHits += 1;
        return { data: [...snapshot.rows], endpoint: "before", source: "shared-market-cache", cacheRevision: snapshot.version,
          all_rows_final: true, complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
          missing_ranges: [], has_tail_gap: false, truncated: false, has_more: true };
      }
    }
    return this.requestCoordinator.fetchKlinesBefore(...args);
  };
  readonly fetchLatestKlines: KlineApi["fetchLatestKlines"] = (...args) => this.requestCoordinator.fetchLatestKlines(...args);
  readonly getMultiStreamUrl: KlineApi["getMultiStreamUrl"] = (...args) => this.api.getMultiStreamUrl(...args);

  read(series: MarketSeries, range?: MarketRange) { return this.cache.read(series, range); }

  warm(series: MarketSeries, options: MarketWarmOptions): MarketWarmLease {
    const plan = planTargetBarRequest({ interval: series.interval, nativeIntervals: options.nativeIntervals,
      desiredTargetBars: Math.min(500, options.limit ?? 500), sourceRowBudget: 10_000 });
    if (this.closed) return { done: Promise.resolve("cancelled"), release() {} };
    const stream = this.warmStreams.acquire(series, options.reason);
    const lease = this.warmQueue.request({ series, owner: options.owner, reason: options.reason,
      limit: plan.targetBars, estimatedSourceRows: plan.estimatedSourceRows });
    const done = lease.done.then(outcome => {
      if (outcome === "warmed" || outcome === "cooldown") stream.retain();
      stream.release();
      return outcome;
    });
    return { done, release: () => { lease.release(); stream.release(); } };
  }

  prepareForeground(series: MarketSeries) { this.warmStreams.promote(series); return this.warmQueue.prepareForeground(series); }

  async recover(series: MarketSeries, options: { from?: number; to?: number; limit?: number; signal?: AbortSignal } = {}): Promise<KlineFetchResult> {
    // Reuse range pagination and endpoint-proof handling. This detached reader
    // has no chart commit adapter and cannot acquire a window's write rights.
    const feed = new SeriesDataFeed({ api: this, getActiveSeries: () => series });
    if (options.from !== undefined && options.to !== undefined) {
      return feed.getRange(series, { start: options.from, end: options.to, commit: "none", repair: "none",
        strict: false, maxPages: 8, source: "manager-recovery", ...(options.signal ? { signal: options.signal } : {}) });
    }
    return feed.getLatest(series, { limit: options.limit ?? 500, commit: "none", repair: "wait", waitMs: 1_500,
      source: "manager-recovery", ...(options.signal ? { signal: options.signal } : {}) });
  }

  readonly fetchKlinesRange: KlineApi["fetchKlinesRange"] = async (...args) => {
    const [symbol, interval, start, end, marketType, exchange, options] = args;
    if (this.closed || options.signal?.aborted) throw aborted();
    // Repair/readback must reach the backend: an old local proof cannot verify
    // a new server correction or establish reconnect freshness.
    if (options.clientContext?.cacheMode !== "network-only" && !options.strict
      && (options.repair === undefined || options.repair === "none")) {
      const snapshot = this.cache.read(identity(symbol, interval, marketType, exchange, options), { from: start, to: end });
      if (snapshot.complete) {
        this.rangeHits += 1;
        return { data: [...snapshot.rows], endpoint: "range", source: "shared-market-cache", cacheRevision: snapshot.version,
          all_rows_final: true, complete: true, retryable: false, history_state: "ready", verified_contiguous: true,
          missing_ranges: [], has_tail_gap: false, truncated: false };
      }
    }
    return this.requestCoordinator.fetchKlinesRange(...args);
  };

  diagnostics() {
    const logical = this.sharedStreams.diagnostics();
    return { ...this.transport.diagnostics(), logicalSubscribers: logical.logicalSubscribers,
      sharedInstruments: logical.entries.length, rejectedRealtime: this.rejectedRealtime, rangeHits: this.rangeHits, beforeHits: this.beforeHits, historyHits: this.historyHits,
      cache: this.cache.diagnostics(), replay: this.replay.diagnostics(), warmStreams: this.warmStreams.diagnostics(), healthRecovery: this.healthRecovery.diagnostics(), warming: this.warmQueue.diagnostics() };
  }

  closeAll(): void {
    if (this.closed) return;
    this.closed = true;
    super.closeAll();
    this.warmQueue.dispose();
    this.warmStreams.dispose();
    this.healthRecovery.dispose();
    if (this.ownsForegroundGate) this.foregroundPreloadGate.dispose();
    this.sharedStreams.closeAll();
    this.transport.closeAll();
    this.requestCoordinator.closeAll();
    this.cache.clear();
  }

  private async acceptHttp(series: MarketSeries, options: KlineRequestOptions, endpoint: NonNullable<KlineFetchResult["endpoint"]>, request: () => Promise<KlineFetchResult>): Promise<KlineFetchResult> {
    if (this.closed || options.signal?.aborted) throw aborted();
    const token = this.cache.beginRead(series);
    try {
      const response = await request();
      if (this.closed || options.signal?.aborted) throw aborted();
      return this.cache.admitResponse(token, { ...response, endpoint });
    } finally { token.release(); }
  }
}
