import { canonicalizeIntervalValue } from "../../../utils/intervals.js";
import type { IntervalString } from "../../../utils/intervals.js";
import type {
  KlineApi,
  KlineBeforeRequestOptions,
  KlineFetchResult,
  KlineHistoryBatchRequest,
  KlineHistoryRequestOptions,
  KlineLatestRequestOptions,
  KlineRangeRequestOptions,
  KlineRequestOptions,
  KlineRequestContext,
} from "../klineContracts.js";
import {
  isLegacyKlineSeriesIdentity,
  klineSeriesIdentityKey,
  type KlineSeriesIdentityInput,
} from "../klineSeriesIdentity.js";

type RequestKind = "before" | "history" | "latest" | "range";

interface RequestConsumer {
  reject(error: unknown): void;
  resolve(result: KlineFetchResult): void;
  signal?: AbortSignal;
  abortListener?: () => void;
  context?: KlineRequestContext;
}

interface SharedRequestEntry {
  consumers: Map<symbol, RequestConsumer>;
  group?: SharedPhysicalGroup;
  historyBatchRequest?: KlineHistoryBatchRequest;
  key: string;
  kind: RequestKind;
  startedAt: number;
}

interface SharedPhysicalGroup {
  controller: AbortController;
  entries: SharedRequestEntry[];
  token: symbol;
  started: boolean;
  admission?: { consumer: RequestConsumer; controller: AbortController; superseded?: boolean };
}

export interface SharedKlineRequestCoordinatorDiagnostics {
  completedPhysical: number;
  joinedLogical: number;
  logicalInflight: number;
  physicalInflight: number;
  requests: Array<{
    ageMs: number;
    consumers: number;
    key: string;
    kind: RequestKind;
  }>;
  totalLogical: number;
  totalPhysical: number;
}

function abortError(): Error {
  if (typeof DOMException === "function") return new DOMException("The operation was aborted", "AbortError");
  const error = new Error("The operation was aborted");
  error.name = "AbortError";
  return error;
}

function intervalIdentity(interval: IntervalString): string {
  return canonicalizeIntervalValue(interval) || String(interval || "").trim();
}

function seriesIdentity(
  symbol: string,
  interval: IntervalString,
  marketType: string,
  exchange: string,
): readonly string[] {
  return [
    String(exchange || "").trim().toLowerCase(),
    String(marketType || "").trim().toLowerCase(),
    String(symbol || "").trim().toUpperCase(),
    intervalIdentity(interval),
  ];
}

function semanticIdentityPart(
  exchange: string,
  identity: KlineSeriesIdentityInput | undefined,
): readonly string[] {
  return isLegacyKlineSeriesIdentity(exchange, identity)
    ? []
    : [klineSeriesIdentityKey(exchange, identity)];
}

function requestKey(kind: RequestKind, identity: readonly unknown[]): string {
  return JSON.stringify([kind, ...identity]);
}

function physicalOptions<TOptions extends KlineRequestOptions>(
  options: TOptions,
  signal: AbortSignal,
): TOptions {
  const { clientContext: _clientContext, ...transport } = options;
  return { ...transport, signal } as TOptions;
}

function readBoundary(options: KlineRequestOptions): readonly unknown[] {
  const context = options.clientContext;
  return context && (context.epoch || context.scope || context.realtimeVersion)
    ? ["read-boundary", context.epoch ?? 0, context.scope ?? null, context.realtimeVersion ?? 0]
    : [];
}

/**
 * Window-scoped exact-request single flight for K-line HTTP work.
 *
 * Each logical caller keeps independent cancellation. The physical fetch is
 * aborted only after every joined caller leaves, so one Cell changing series
 * cannot cancel another Cell that is waiting for the same immutable result.
 */
export class SharedKlineRequestCoordinator implements KlineApi {
  private readonly api: KlineApi;
  private readonly entries = new Map<string, SharedRequestEntry>();
  private readonly pendingHistory = new Set<SharedRequestEntry>();
  private readonly physicalGroups = new Map<symbol, SharedPhysicalGroup>();
  private historyFlushScheduled = false;
  private totalLogical = 0;
  private totalPhysical = 0;
  private joinedLogical = 0;
  private completedPhysical = 0;

  constructor(api: KlineApi, private readonly batchHistory = true) {
    this.api = api;
  }

  fetchKlinesHistory(
    symbol: string,
    interval: IntervalString,
    days: number | null | undefined,
    marketType: string,
    exchange: string,
    options: KlineHistoryRequestOptions,
  ): Promise<KlineFetchResult> {
    const identity = [
      ...seriesIdentity(symbol, interval, marketType, exchange),
      ...semanticIdentityPart(exchange, options.seriesIdentity),
      days ?? null,
      options.countBack ?? null,
      options.maxWaitMs ?? null,
      options.intent ?? null,
      options.demandScope ?? null,
      options.demandGeneration ?? null,
      ...readBoundary(options),
    ];
    return this.join(
      "history",
      requestKey("history", identity),
      options,
      (signal) => this.api.fetchKlinesHistory(
        symbol,
        interval,
        days,
        marketType,
        exchange,
        physicalOptions(options, signal),
      ),
      this.batchHistory && this.api.fetchKlinesHistoryBatch
        ? {
            symbol,
            interval,
            days,
            marketType,
            exchange,
            options: {
              ...(options.countBack === undefined ? {} : { countBack: options.countBack }),
              ...(options.maxWaitMs === undefined ? {} : { maxWaitMs: options.maxWaitMs }),
              ...(options.intent === undefined ? {} : { intent: options.intent }),
              ...(options.demandScope === undefined ? {} : { demandScope: options.demandScope }),
              ...(options.demandGeneration === undefined
                ? {}
                : { demandGeneration: options.demandGeneration }),
              ...(options.seriesIdentity === undefined
                ? {}
                : { seriesIdentity: options.seriesIdentity }),
            },
          }
        : undefined,
    );
  }

  fetchKlinesBefore(
    symbol: string,
    interval: IntervalString,
    before: Parameters<KlineApi["fetchKlinesBefore"]>[2],
    bars: number,
    marketType: string,
    exchange: string,
    options: KlineBeforeRequestOptions,
  ): Promise<KlineFetchResult> {
    const identity = [
      ...seriesIdentity(symbol, interval, marketType, exchange),
      ...semanticIdentityPart(exchange, options.seriesIdentity),
      before ?? null,
      bars,
      options.maxWaitMs ?? null,
      options.demandScope ?? null,
      options.demandGeneration ?? null,
      ...readBoundary(options),
    ];
    return this.join(
      "before",
      requestKey("before", identity),
      options,
      (signal) => this.api.fetchKlinesBefore(
        symbol,
        interval,
        before,
        bars,
        marketType,
        exchange,
        physicalOptions(options, signal),
      ),
    );
  }

  fetchKlinesRange(
    symbol: string,
    interval: IntervalString,
    start: Parameters<KlineApi["fetchKlinesRange"]>[2],
    end: Parameters<KlineApi["fetchKlinesRange"]>[3],
    marketType: string,
    exchange: string,
    options: KlineRangeRequestOptions,
  ): Promise<KlineFetchResult> {
    const identity = [
      ...seriesIdentity(symbol, interval, marketType, exchange),
      ...semanticIdentityPart(exchange, options.seriesIdentity),
      start,
      end,
      options.repair ?? null,
      options.waitMs ?? null,
      options.strict ?? null,
      options.demandScope ?? null,
      options.demandGeneration ?? null,
      ...readBoundary(options),
    ];
    return this.join(
      "range",
      requestKey("range", identity),
      options,
      (signal) => this.api.fetchKlinesRange(
        symbol,
        interval,
        start,
        end,
        marketType,
        exchange,
        physicalOptions(options, signal),
      ),
    );
  }

  fetchLatestKlines(
    symbol: string,
    interval: IntervalString,
    limit: number,
    marketType: string,
    exchange: string,
    source: string,
    options: KlineLatestRequestOptions,
  ): Promise<KlineFetchResult> {
    const identity = [
      ...seriesIdentity(symbol, interval, marketType, exchange),
      ...semanticIdentityPart(exchange, options.seriesIdentity),
      limit,
      String(source || ""),
      options.repair ?? "none",
      options.waitMs ?? null,
      options.demandScope ?? null,
      options.demandGeneration ?? null,
      ...readBoundary(options),
    ];
    return this.join(
      "latest",
      requestKey("latest", identity),
      options,
      (signal) => this.api.fetchLatestKlines(
        symbol,
        interval,
        limit,
        marketType,
        exchange,
        source,
        physicalOptions(options, signal),
      ),
    );
  }

  getMultiStreamUrl(symbol: string, marketType: string, exchange: string): string {
    return this.api.getMultiStreamUrl(symbol, marketType, exchange);
  }

  diagnostics(now = Date.now()): SharedKlineRequestCoordinatorDiagnostics {
    let logicalInflight = 0;
    const requests = [...this.entries.values()].slice(0, 64).map((entry) => {
      logicalInflight += entry.consumers.size;
      return {
        ageMs: Math.max(0, now - entry.startedAt),
        consumers: entry.consumers.size,
        key: entry.key,
        kind: entry.kind,
      };
    });
    if (this.entries.size > requests.length) {
      for (const entry of [...this.entries.values()].slice(requests.length)) {
        logicalInflight += entry.consumers.size;
      }
    }
    return {
      completedPhysical: this.completedPhysical,
      joinedLogical: this.joinedLogical,
      logicalInflight,
      physicalInflight: this.physicalGroups.size,
      requests,
      totalLogical: this.totalLogical,
      totalPhysical: this.totalPhysical,
    };
  }

  closeAll(): void {
    const entries = [...this.entries.values()];
    this.entries.clear();
    this.pendingHistory.clear();
    for (const group of this.physicalGroups.values()) {
      group.controller.abort();
      if (!group.started) group.admission?.controller.abort();
    }
    this.physicalGroups.clear();
    for (const entry of entries) {
      this.settle(entry, "reject", abortError());
    }
  }

  private join(
    kind: RequestKind,
    key: string,
    options: KlineRequestOptions,
    request: (signal: AbortSignal) => Promise<KlineFetchResult>,
    historyBatchRequest?: KlineHistoryBatchRequest,
  ): Promise<KlineFetchResult> {
    const { signal } = options;
    this.totalLogical += 1;
    if (signal?.aborted) return Promise.reject(abortError());

    let entry = this.entries.get(key);
    if (!entry) {
      entry = {
        consumers: new Map(),
        ...(historyBatchRequest === undefined ? {} : { historyBatchRequest }),
        key,
        kind,
        startedAt: Date.now(),
      };
      this.entries.set(key, entry);
      if (historyBatchRequest && this.api.fetchKlinesHistoryBatch) {
        this.pendingHistory.add(entry);
        this.scheduleHistoryFlush();
      } else {
        this.startSingle(entry, request);
      }
    } else {
      this.joinedLogical += 1;
    }

    const ownedEntry = entry;
    return new Promise<KlineFetchResult>((resolve, reject) => {
      const token = Symbol(key);
      const consumer: RequestConsumer = { reject, resolve };
      if (options.clientContext) consumer.context = options.clientContext;
      if (signal) {
        const abortListener = () => {
          if (!ownedEntry.consumers.delete(token)) return;
          signal.removeEventListener("abort", abortListener);
          reject(abortError());
          const group = ownedEntry.group;
          if (group?.admission?.consumer === consumer && !group.started) {
            group.admission.controller.abort();
          }
          if (ownedEntry.consumers.size === 0 && this.entries.get(key) === ownedEntry) {
            this.entries.delete(key);
            this.pendingHistory.delete(ownedEntry);
            this.abortGroupIfUnowned(ownedEntry.group);
          }
        };
        consumer.signal = signal;
        consumer.abortListener = abortListener;
        signal.addEventListener("abort", abortListener, { once: true });
      }
      ownedEntry.consumers.set(token, consumer);
      const group = ownedEntry.group;
      if (group?.admission && !group.started
        && (consumer.context?.priority ?? 0) < (group.admission.consumer.context?.priority ?? 0)) {
        group.admission.superseded = true;
        group.admission.controller.abort();
      }
    });
  }

  private startSingle(
    entry: SharedRequestEntry,
    request: (signal: AbortSignal) => Promise<KlineFetchResult>,
  ): void {
    const group = this.createPhysicalGroup([entry]);
    void Promise.resolve()
      .then(() => this.runScheduled(group, () => request(group.controller.signal)))
      .then(
        (result) => this.finishGroup(group, [{ outcome: "resolve", value: result }]),
        (error) => this.finishGroup(group, [{ outcome: "reject", value: error }]),
      );
  }

  private scheduleHistoryFlush(): void {
    if (this.historyFlushScheduled) return;
    this.historyFlushScheduled = true;
    queueMicrotask(() => {
      this.historyFlushScheduled = false;
      this.flushHistory();
    });
  }

  private flushHistory(): void {
    const available = [...this.pendingHistory].filter((entry) => (
      this.entries.get(entry.key) === entry && entry.consumers.size > 0
    ));
    for (const entry of available) this.pendingHistory.delete(entry);
    for (let offset = 0; offset < available.length; offset += 16) {
      const entries = available.slice(offset, offset + 16);
      if (entries.length === 1 || !this.api.fetchKlinesHistoryBatch) {
        const entry = entries[0];
        if (!entry) continue;
        const item = entry.historyBatchRequest;
        if (!item) continue;
        this.startSingle(entry, (signal) => this.api.fetchKlinesHistory(
          item.symbol,
          item.interval,
          item.days,
          item.marketType,
          item.exchange,
          physicalOptions(item.options, signal),
        ));
        continue;
      }
      const group = this.createPhysicalGroup(entries);
      const items = entries.map((entry) => entry.historyBatchRequest as KlineHistoryBatchRequest);
      void this.runScheduled(group, () => this.api.fetchKlinesHistoryBatch!(items, { signal: group.controller.signal })).then(
        (outcomes) => {
          if (outcomes.length !== entries.length) {
            throw new Error("History batch response length did not match the request length");
          }
          this.finishGroup(group, outcomes.map((outcome) => outcome.ok
            ? { outcome: "resolve" as const, value: outcome.result }
            : { outcome: "reject" as const, value: outcome.error }));
        },
        (error: unknown) => this.finishGroup(
          group,
          entries.map(() => ({ outcome: "reject" as const, value: error })),
        ),
      ).catch((error: unknown) => this.finishGroup(
        group,
        entries.map(() => ({ outcome: "reject" as const, value: error })),
      ));
    }
  }

  private createPhysicalGroup(entries: SharedRequestEntry[]): SharedPhysicalGroup {
    const group: SharedPhysicalGroup = {
      controller: new AbortController(),
      entries,
      token: Symbol("physical-kline-request"),
      started: false,
    };
    for (const entry of entries) entry.group = group;
    this.physicalGroups.set(group.token, group);
    this.totalPhysical += 1;
    return group;
  }

  private abortGroupIfUnowned(group: SharedPhysicalGroup | undefined): void {
    if (!group) return;
    const hasOwner = group.entries.some((entry) => (
      this.entries.get(entry.key) === entry && entry.consumers.size > 0
    ));
    if (!hasOwner) {
      group.controller.abort();
      if (!group.started) group.admission?.controller.abort();
    }
  }

  private async runScheduled<T>(group: SharedPhysicalGroup, request: () => Promise<T>): Promise<T> {
    // Join callers before reserving scheduler capacity. A departing sponsor
    // may relinquish queued admission, but cannot cancel another consumer.
    while (!group.controller.signal.aborted) {
      const candidate = group.entries.flatMap((entry) => (
        [...entry.consumers].map(([token, consumer]) => ({ entry, token, consumer }))
      )).sort((a, b) => (a.consumer.context?.priority ?? 0) - (b.consumer.context?.priority ?? 0))[0];
      if (!candidate) throw abortError();
      const { entry, token, consumer } = candidate;
      const controller = new AbortController();
      group.admission = { consumer, controller };
      const execute = () => {
        if (controller.signal.aborted || group.controller.signal.aborted) throw abortError();
        group.started = true;
        return request();
      };
      try {
        return await (consumer.context?.schedule
          ? consumer.context.schedule(execute, controller.signal)
          : execute());
      } catch (error) {
        if (group.started) throw error;
        if (group.admission?.superseded) continue;
        // A scheduler may reject one Cell (hidden/unmounted). Remove only that
        // logical caller and let another live owner sponsor the same request.
        if (entry.consumers.delete(token)) {
          if (consumer.signal && consumer.abortListener) {
            consumer.signal.removeEventListener("abort", consumer.abortListener);
          }
          consumer.reject(error);
          if (entry.consumers.size === 0 && this.entries.get(entry.key) === entry) {
            this.entries.delete(entry.key);
          }
        }
      } finally {
        delete group.admission;
      }
    }
    throw abortError();
  }

  private finishGroup(
    group: SharedPhysicalGroup,
    outcomes: Array<{ outcome: "reject" | "resolve"; value: unknown }>,
  ): void {
    if (!this.physicalGroups.delete(group.token)) return;
    this.completedPhysical += 1;
    group.entries.forEach((entry, index) => {
      if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
      delete entry.group;
      const result = outcomes[index] ?? {
        outcome: "reject" as const,
        value: new Error("Missing physical request outcome"),
      };
      this.settle(entry, result.outcome, result.value);
    });
  }

  private settle(
    entry: SharedRequestEntry,
    outcome: "reject" | "resolve",
    value: unknown,
  ): void {
    const consumers = [...entry.consumers.values()];
    entry.consumers.clear();
    for (const consumer of consumers) {
      if (consumer.signal && consumer.abortListener) {
        consumer.signal.removeEventListener("abort", consumer.abortListener);
      }
      if (outcome === "resolve") consumer.resolve(value as KlineFetchResult);
      else consumer.reject(value);
    }
  }
}

const adapters = new WeakMap<KlineApi, SharedKlineRequestCoordinator>();

/** Reuse a supplied workspace owner; raw adapters get the same cancellation contract. */
export function sharedKlineRequests(api: KlineApi): SharedKlineRequestCoordinator {
  if (api instanceof SharedKlineRequestCoordinator) return api;
  let coordinator = adapters.get(api);
  if (!coordinator) {
    coordinator = new SharedKlineRequestCoordinator(api, false);
    adapters.set(api, coordinator);
  }
  return coordinator;
}
