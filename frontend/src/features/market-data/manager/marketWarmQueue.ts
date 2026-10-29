import type { KlineFetchResult } from "../klineContracts.js";
import type { MarketSeries } from "../marketDataTypes.js";
import type { ForegroundPreloadGate, PreloadLease } from "../foregroundPreloadGate.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";

export type WarmReason = "hover" | "frequent" | "watchlist";
export type WarmOutcome = "warmed" | "cancelled" | "budget" | "cooldown" | "failed";
export interface MarketWarmRequest {
  series: MarketSeries;
  owner: string;
  reason: WarmReason;
  limit: number;
  estimatedSourceRows: number;
}
export interface MarketWarmLease { done: Promise<WarmOutcome>; release(): void }
export interface MarketWarmQueueOptions {
  gate: ForegroundPreloadGate;
  read(request: MarketWarmRequest, signal: AbortSignal): Promise<KlineFetchResult>;
  maxPending?: number;
  maxConcurrent?: number;
  maxSourceRows?: number;
  sourceRowsPerMinute?: number;
  maxInflightBytes?: number;
  cooldownMs?: number;
  now?: () => number;
  schedule?: (work: () => void, delay: number) => unknown;
  cancel?: (handle: unknown) => void;
}
interface Waiter { resolve(value: KlineFetchResult): void; reject(error: unknown): void; cleanup(): void }
interface Job {
  key: string;
  request: MarketWarmRequest;
  consumers: Map<symbol, (outcome: WarmOutcome) => void>;
  foreground: Map<symbol, Waiter>;
  holds: Set<symbol>;
  active: { controller: AbortController; lease: PreloadLease } | null;
  promoted: boolean;
  settled: boolean;
}

const priority: Record<WarmReason, number> = { hover: 0, frequent: 1, watchlist: 2 };
const keyFor = (series: MarketSeries, limit: number) => `${buildSeriesWindowKey(series)}|viewport:${limit}`;
const aborted = () => new DOMException("The operation was aborted", "AbortError");

/** Shared speculative budget and lifetime. It owns demand leases, never rows.
 * Foreground promotion releases the preload slot before the foreground gate
 * preempts it, while preserving the same in-flight HTTP admission. */
export class MarketWarmQueue {
  private readonly jobs = new Map<string, Job>();
  private readonly recent = new Map<string, number>();
  private readonly spent: Array<{ at: number; rows: number }> = [];
  private readonly now: () => number;
  private readonly schedule: NonNullable<MarketWarmQueueOptions["schedule"]>;
  private readonly cancel: NonNullable<MarketWarmQueueOptions["cancel"]>;
  private readonly unsubscribe: () => void;
  private wake: unknown = null;
  private disposed = false;
  private pumping = false;
  private completed = 0;
  private promoted = 0;
  private rejected = 0;

  constructor(private readonly options: MarketWarmQueueOptions) {
    this.now = options.now ?? Date.now;
    this.schedule = options.schedule ?? ((work, delay) => setTimeout(work, delay));
    this.cancel = options.cancel ?? (handle => clearTimeout(handle as ReturnType<typeof setTimeout>));
    this.unsubscribe = options.gate.subscribe(() => this.pump());
  }

  request(request: MarketWarmRequest): MarketWarmLease {
    const done = (outcome: WarmOutcome): MarketWarmLease => ({ done: Promise.resolve(outcome), release() {} });
    if (this.disposed) return done("cancelled");
    const key = keyFor(request.series, request.limit);
    if ((this.recent.get(key) ?? 0) > this.now()) return done("cooldown");
    const maxSource = this.options.maxSourceRows ?? 10_000;
    if (!Number.isInteger(request.limit) || request.limit < 1 || request.limit > 500
      || !Number.isInteger(request.estimatedSourceRows) || request.estimatedSourceRows < request.limit
      || request.estimatedSourceRows > maxSource
      || request.estimatedSourceRows > (this.options.sourceRowsPerMinute ?? 30_000)
      || request.limit * 200 > (this.options.maxInflightBytes ?? 2_000_000)) {
      this.rejected += 1; return done("budget");
    }
    let job = this.jobs.get(key);
    if (!job) {
      if (this.jobs.size >= (this.options.maxPending ?? 16)) { this.rejected += 1; return done("budget"); }
      job = { key, request: { ...request, series: { ...request.series } }, consumers: new Map(),
        foreground: new Map(), holds: new Set(), active: null, promoted: false, settled: false };
      this.jobs.set(key, job);
    } else if (priority[request.reason] < priority[job.request.reason]) job.request = { ...job.request, reason: request.reason };
    const id = Symbol(request.owner), target = job;
    const promise = new Promise<WarmOutcome>(resolve => target.consumers.set(id, resolve));
    this.pump();
    return { done: promise, release: () => {
      const resolve = target.consumers.get(id);
      target.consumers.delete(id); resolve?.("cancelled");
      this.releaseUnused(target);
    } };
  }

  /** Called synchronously at selection intent, before React's busy effects.
   * Queued work is left to the normal foreground request; only running work
   * can be transferred without bypassing the foreground scheduler. */
  prepareForeground(series: MarketSeries): { release(): void } {
    const held: Array<{ job: Job; id: symbol }> = [];
    for (const job of this.jobs.values()) {
      if (!job.active || job.active.controller.signal.aborted
        || buildSeriesWindowKey(job.request.series) !== buildSeriesWindowKey(series)) continue;
      const id = Symbol("foreground-handoff");
      job.holds.add(id); held.push({ job, id });
      if (!job.promoted) {
        job.promoted = true; this.promoted += 1;
        this.options.gate.release(job.active.lease);
      }
    }
    return { release: () => { for (const { job, id } of held) { job.holds.delete(id); this.releaseUnused(job); } } };
  }

  joinForeground(series: MarketSeries, limit: number, signal?: AbortSignal): Promise<KlineFetchResult> | null {
    const job = this.jobs.get(keyFor(series, limit));
    if (!job?.promoted || !job.active || job.active.controller.signal.aborted) return null;
    if (signal?.aborted) return Promise.reject(aborted());
    const id = Symbol("foreground-reader");
    return new Promise((resolve, reject) => {
      const onAbort = () => {
        job.foreground.delete(id); signal?.removeEventListener("abort", onAbort);
        reject(aborted()); this.releaseUnused(job);
      };
      job.foreground.set(id, { resolve, reject, cleanup: () => signal?.removeEventListener("abort", onAbort) });
      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }

  diagnostics() {
    const active = [...this.jobs.values()].filter(job => job.active);
    return { queued: this.jobs.size - active.length, active: active.length,
      inflightBytes: active.reduce((sum, job) => sum + job.request.limit * 200, 0),
      completed: this.completed, promoted: this.promoted, rejected: this.rejected };
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true; this.unsubscribe();
    if (this.wake !== null) this.cancel(this.wake);
    this.wake = null;
    for (const job of [...this.jobs.values()]) this.finish(job, "cancelled", undefined, aborted());
    this.recent.clear(); this.spent.length = 0;
  }

  private pump(): void {
    if (this.disposed || this.pumping) return;
    this.pumping = true;
    try {
      const now = this.now();
      while (this.spent.length && this.spent[0]!.at + 60_000 <= now) this.spent.shift();
      for (const [key, until] of this.recent) if (until <= now) this.recent.delete(key);
      const candidates = [...this.jobs.values()].filter(job => !job.active && !job.settled)
        .sort((a, b) => priority[a.request.reason] - priority[b.request.reason]);
      // Reconcile our local priority order with the gate's FIFO. A previously
      // queued watchlist owner must not strand a later hover at the queue head.
      for (const job of candidates) this.options.gate.cancelQueued(`market-warm:${job.key}`);
      for (const job of candidates) {
        const active = [...this.jobs.values()].filter(item => item.active);
        if (active.length >= (this.options.maxConcurrent ?? 2)) break;
        if (active.reduce((sum, item) => sum + item.request.limit * 200, 0) + job.request.limit * 200
          > (this.options.maxInflightBytes ?? 2_000_000)) continue;
        if (this.spent.reduce((sum, item) => sum + item.rows, 0) + job.request.estimatedSourceRows
          > (this.options.sourceRowsPerMinute ?? 30_000)) {
          if (this.wake === null && this.spent.length) this.wake = this.schedule(() => {
            this.wake = null; this.pump();
          }, Math.max(1, this.spent[0]!.at + 60_000 - now));
          continue;
        }
        const lease = job.request.reason === "hover"
          ? this.options.gate.tryAcquireIntentPreload(`market-warm:${job.key}`)
          : this.options.gate.tryAcquirePreload(`market-warm:${job.key}`);
        if (!lease) break;
        job.active = { controller: lease.controller, lease };
        this.spent.push({ at: now, rows: job.request.estimatedSourceRows });
        const attempt = job.active;
        void Promise.resolve().then(() => {
          if (attempt.controller.signal.aborted || job.settled) throw aborted();
          return this.options.read(job.request, attempt.controller.signal);
        }).then(result => {
          if (attempt.controller.signal.aborted || job.settled) throw aborted();
          this.completed += 1;
          this.finish(job, "warmed", result);
        }).catch(error => {
          if (job.settled) return;
          if (attempt.controller.signal.aborted && job.consumers.size && !job.promoted && !this.disposed) {
            job.active = null;
            this.options.gate.release(attempt.lease);
            this.pump();
          } else this.finish(job, attempt.controller.signal.aborted ? "cancelled" : "failed", undefined, error);
        });
      }
    } finally { this.pumping = false; }
  }

  private releaseUnused(job: Job): void {
    if (!job.settled && !job.consumers.size && !job.holds.size && !job.foreground.size) this.finish(job, "cancelled", undefined, aborted());
  }

  private finish(job: Job, outcome: WarmOutcome, result?: KlineFetchResult, error?: unknown): void {
    if (job.settled) return;
    job.settled = true; this.jobs.delete(job.key);
    this.options.gate.cancelQueued(`market-warm:${job.key}`);
    if (outcome === "warmed" || outcome === "failed") {
      this.recent.set(job.key, this.now() + (this.options.cooldownMs ?? 30_000));
      while (this.recent.size > 128) this.recent.delete(this.recent.keys().next().value!);
    }
    if (outcome !== "warmed") job.active?.controller.abort();
    for (const resolve of job.consumers.values()) resolve(outcome);
    job.consumers.clear();
    for (const waiter of job.foreground.values()) {
      waiter.cleanup();
      if (result) waiter.resolve({ ...result, ...(result.data ? { data: [...result.data] } : {}) });
      else waiter.reject(error ?? aborted());
    }
    job.foreground.clear(); job.holds.clear();
    if (job.active) this.options.gate.release(job.active.lease);
    job.active = null;
    this.pump();
  }
}
