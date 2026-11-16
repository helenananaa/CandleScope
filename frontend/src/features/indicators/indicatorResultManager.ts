import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { MarketInputVersion } from "../market-data/manager/sharedMarketCache.js";
import type { IndicatorCacheInputSource } from "./indicatorInputBinding.js";
import { isFrontendScript } from "./frontendScriptContract.js";
import { indicatorRequestKey } from "./indicatorRequestBroker.js";
import { indicatorRuntimeAdapter } from "./indicatorRuntimeAdapter.js";
import {
  buildIndicatorResultCacheKey, cacheIndicatorSnapshot, getCachedIndicatorResult,
  patchCachedIndicatorResult, replaceCachedIndicatorRange, upsertCachedIndicatorLinePoint,
} from "./indicatorResultCacheStore.js";
import type {
  IndicatorCacheContext, IndicatorCacheEntry, IndicatorCacheMetadata, IndicatorComputeRequest,
  IndicatorDefinition, IndicatorParameterSchema, IndicatorPayloadEnvelope, IndicatorRange, NormalizedIndicatorPayload,
} from "./indicatorTypes.js";

type Context = Partial<IndicatorCacheContext>;
type Adapter = ReturnType<typeof indicatorRuntimeAdapter>;
export interface IndicatorResultCommit {
  key: string;
  indicatorId: string;
  contentVersion: number;
  adapter: Adapter;
  operation: "snapshot" | "patch" | "range" | "point";
  taskKey?: string;
}
export interface IndicatorResultTask {
  readonly manager: IndicatorResultManager;
  readonly key: string;
  readonly taskKey: string;
  isCurrent(): boolean;
}
interface ComputedResult { payload: IndicatorPayloadEnvelope; version: MarketInputVersion; bytes: number }

function freeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

/** Workspace result ingress. Execution/stream owners fence their task and
 * session generations before calling it; this boundary additionally enforces
 * input ownership, immutable cache commit, then result notification.
 *
 * The small semantic JS cache holds worker output before chart-specific IDs
 * are attached. Existing result cache entries remain private projections with
 * their range/revision/GC contracts; hosted script sessions are never pooled.
 */
export class IndicatorResultManager {
  private readonly listeners = new Set<(commit: IndicatorResultCommit) => void>();
  private readonly computed = new Map<string, ComputedResult>();
  private bytes = 0;
  private commits = 0;
  private rejected = 0;
  private reused = 0;
  private disposed = false;
  constructor(private readonly inputSource?: IndicatorCacheInputSource,
    private readonly limits = { entries: 80, bytes: 4 * 1024 * 1024 }) {}

  subscribe(listener: (commit: IndicatorResultCommit) => void): () => void {
    if (this.disposed) return () => {};
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  /** Capture before dispatch. A consumer's cancellation/generation predicate
   * does not own the physical computation shared with other consumers. */
  begin(indicator: IndicatorDefinition, context: Context, taskKey: string, current: () => boolean): IndicatorResultTask {
    let retired = false;
    return Object.freeze({ manager: this, key: buildIndicatorResultCacheKey(indicator, context), taskKey,
      isCurrent: () => { retired ||= this.disposed || !current(); return !retired; } });
  }

  snapshot = (indicator: IndicatorDefinition | null | undefined, context: Context,
    normalized: NormalizedIndicatorPayload, schema: IndicatorParameterSchema[] = [], metadata: IndicatorCacheMetadata = {}, task?: IndicatorResultTask) =>
    this.commit(indicator, context, "snapshot", () => cacheIndicatorSnapshot(indicator, context, normalized, schema, metadata), task);

  patch = (indicator: IndicatorDefinition | null | undefined, context: Context,
    normalized: NormalizedIndicatorPayload, metadata: IndicatorCacheMetadata = {}) =>
    this.commit(indicator, context, "patch", () => patchCachedIndicatorResult(indicator, context, normalized, metadata));

  replaceRange = (indicator: IndicatorDefinition | null | undefined, context: Context,
    normalized: NormalizedIndicatorPayload, range: IndicatorRange, metadata: IndicatorCacheMetadata = {}) =>
    this.commit(indicator, context, "range", () => replaceCachedIndicatorRange(indicator, context, normalized, range, metadata));

  point = (...args: Parameters<typeof upsertCachedIndicatorLinePoint>) =>
    this.commit(args[0], args[1], "point", () => upsertCachedIndicatorLinePoint(...args));

  read(indicator: IndicatorDefinition, context: Context) {
    const adapter = indicatorRuntimeAdapter(indicator, context);
    const result = this.disposed || (this.inputSource && context.inputSource !== this.inputSource)
      ? null : getCachedIndicatorResult(indicator, context);
    return { adapter, state: !result ? "unavailable" as const : result.staleSegments.length ? "stale" as const : "ready" as const, result };
  }

  /** Exact provided input only. Forming previews make progress via their
   * closed-prefix task fence, but cannot certify a reusable completed result. */
  captureCompute(request: IndicatorComputeRequest) {
    if (!this.inputSource || !isFrontendScript(request) || !request.ohlcv.length
      || request.ohlcv.some(row => row.is_closed !== true)) return null;
    const series = { ...request.seriesIdentity, exchange: request.exchange || "binance", marketType: request.marketType || "spot",
      symbol: request.symbol || "", interval: request.interval || "" };
    const version = this.inputSource.captureProvided(series, request.ohlcv as KlineBar[]);
    if (!version) return null;
    const key = indicatorRequestKey(request);
    return { key, version };
  }

  reuseCompute(ticket: ReturnType<IndicatorResultManager["captureCompute"]>): IndicatorPayloadEnvelope | null {
    if (!ticket || this.disposed) return null;
    const entry = this.computed.get(ticket.key);
    if (!entry) return null;
    if (!entry.version.isCurrent() || !ticket.version.isCurrent()) { this.removeComputed(ticket.key); return null; }
    this.computed.delete(ticket.key); this.computed.set(ticket.key, entry); this.reused += 1;
    return entry.payload;
  }

  publishCompute(ticket: ReturnType<IndicatorResultManager["captureCompute"]>, payload: IndicatorPayloadEnvelope): IndicatorPayloadEnvelope {
    const owned = freeze(structuredClone(payload));
    if (!ticket || this.disposed || payload.ok !== true || !ticket.version.isCurrent()) return owned;
    // Count key storage too: exact OHLCV equality is intentionally not replaced
    // by a digest. Oversized work can execute without becoming resident.
    const bytes = new TextEncoder().encode(ticket.key + JSON.stringify(payload)).byteLength;
    if (bytes > this.limits.bytes) return owned;
    this.removeComputed(ticket.key);
    this.computed.set(ticket.key, { payload: owned, version: ticket.version, bytes });
    this.bytes += bytes;
    while (this.computed.size > this.limits.entries || this.bytes > this.limits.bytes) this.removeComputed(this.computed.keys().next().value!);
    return owned;
  }

  diagnostics() { return { commits: this.commits, rejected: this.rejected, reused: this.reused,
    completed: this.computed.size, bytes: this.bytes, subscribers: this.listeners.size }; }
  dispose(): void { this.disposed = true; this.listeners.clear(); this.computed.clear(); this.bytes = 0; }

  private removeComputed(key: string): void {
    const entry = this.computed.get(key);
    if (entry) this.bytes -= entry.bytes;
    this.computed.delete(key);
  }
  private commit(indicator: IndicatorDefinition | null | undefined, context: Context,
    operation: IndicatorResultCommit["operation"], write: () => IndicatorCacheEntry | null, task?: IndicatorResultTask): IndicatorCacheEntry | null {
    if (this.disposed || !indicator?.id || (this.inputSource && context.inputSource !== this.inputSource)
      || (task && (task.manager !== this || !task.isCurrent() || task.key !== buildIndicatorResultCacheKey(indicator, context)))) {
      this.rejected += 1; return null;
    }
    const adapter = indicatorRuntimeAdapter(indicator, context);
    const entry = write();
    if (!entry) { this.rejected += 1; return null; }
    this.commits += 1;
    const event = freeze({ key: buildIndicatorResultCacheKey(indicator, context), indicatorId: indicator.id,
      contentVersion: entry.contentVersion, adapter, operation, ...(task ? { taskKey: task.taskKey } : {}) });
    for (const listener of this.listeners) {
      try { listener(event); } catch (error) { console.warn("Indicator result subscriber failed", error); }
    }
    return entry;
  }
}

/** Offline/provided-bars controllers retain their own input/lifecycle fences. */
export const standaloneIndicatorResults = new IndicatorResultManager();
