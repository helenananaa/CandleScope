import type {
  KlineApi, KlineFetchResult, KlineHistoryBatchOutcome, KlineRequestOptions, KlineStreamFactory,
} from "../klineContracts.js";
import type { MarketSeries } from "../marketDataTypes.js";
import { SharedKlineRequestCoordinator } from "../feed/sharedKlineRequestCoordinator.js";
import { SharedKlineStreamCoordinator } from "../feed/sharedKlineStreamCoordinator.js";
import { SharedMarketCache, type MarketCacheOptions, type MarketReadToken } from "./sharedMarketCache.js";

interface StreamTransport {
  subscribe: KlineStreamFactory;
  closeAll(): void;
  diagnostics(): object;
}
export interface MarketDataManagerOptions {
  api: KlineApi;
  streams: StreamTransport;
  batchHistory?: boolean;
  cache?: MarketCacheOptions;
}

function identity(symbol: string, interval: string, marketType: string, exchange: string, options: KlineRequestOptions): MarketSeries {
  return { ...options.seriesIdentity, symbol, interval, marketType, exchange };
}

function aborted(): DOMException { return new DOMException("The operation was aborted", "AbortError"); }

/** Frontend workspace data boundary. Physical responses are admitted once before
 * fan-out. Chart/watchlist consumers own independent request/stream leases;
 * cache facts contain no viewport or chart-selection state. */
export class MarketDataManager implements KlineApi {
  readonly ownsRequestLeases = true;
  readonly cache: SharedMarketCache;
  readonly requestCoordinator: SharedKlineRequestCoordinator;
  private readonly sharedStreams: SharedKlineStreamCoordinator;
  private readonly transport: StreamTransport;
  private readonly api: KlineApi;
  private closed = false;
  private rejectedRealtime = 0;
  private rangeHits = 0;

  constructor(options: MarketDataManagerOptions) {
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
    this.sharedStreams = new SharedKlineStreamCoordinator(api, {
      createPhysicalStream: (series, streamOptions) => this.transport.subscribe(series, {
        ...streamOptions,
        onKline: (event, controller) => {
          if (this.closed) return;
          const accepted = this.cache.admitRealtime({ ...series, interval: event.interval }, event.tick,
            typeof event.message.event_type === "string" ? event.message.event_type : undefined);
          if (!accepted.accepted || !accepted.row) { this.rejectedRealtime += 1; return; }
          streamOptions.onKline?.({ ...event, tick: accepted.row, message: { ...event.message, data: accepted.row } }, controller);
        },
        onError: (event, controller) => {
          this.cache.markDisconnected(series);
          streamOptions.onError?.(event, controller);
        },
        onClose: (event, controller) => {
          this.cache.markDisconnected(series);
          streamOptions.onClose?.(event, controller);
        },
      }),
    });
  }

  readonly subscribe: KlineStreamFactory = (series, options) => {
    if (this.closed) throw new Error("MarketDataManager is closed");
    return this.sharedStreams.subscribe(series, options);
  };

  readonly fetchKlinesHistory: KlineApi["fetchKlinesHistory"] = (...args) => this.requestCoordinator.fetchKlinesHistory(...args);
  readonly fetchKlinesBefore: KlineApi["fetchKlinesBefore"] = (...args) => this.requestCoordinator.fetchKlinesBefore(...args);
  readonly fetchLatestKlines: KlineApi["fetchLatestKlines"] = (...args) => this.requestCoordinator.fetchLatestKlines(...args);
  readonly getMultiStreamUrl: KlineApi["getMultiStreamUrl"] = (...args) => this.api.getMultiStreamUrl(...args);

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
      sharedInstruments: logical.entries.length, rejectedRealtime: this.rejectedRealtime, rangeHits: this.rangeHits,
      cache: this.cache.diagnostics() };
  }

  closeAll(): void {
    if (this.closed) return;
    this.closed = true;
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
