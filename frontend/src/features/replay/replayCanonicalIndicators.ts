import { API_BASE } from "../../services/apiConfig.js";
import { computeIndicatorBatch } from "../../services/indicatorApi.js";
import { parseIndicatorPayloadEnvelope } from "../indicators/indicatorContracts.js";
import type { IndicatorComputeBatchExecutor } from "../indicators/indicatorComputeController.js";
import type { IndicatorComputeBatchJob, IndicatorPayloadEnvelope } from "../indicators/indicatorTypes.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { ReplayBuiltinSeed } from "./replayBuiltinCompute.js";
import { ReplayHistoryProvider, type ReplayHistoryExcludedRange, type ReplayHistoryIdentity } from "./replayHistoryProvider.js";
import { replayDisplayBarToKline } from "./replaySeriesProjection.js";
import { replayUsesAuthoritativeSourceBucketProjection } from "./replayViewerProjection.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import type { ReplayDigest, ReplayDisplayBar } from "./replayTypes.js";
import { ReplayIndicatorProgress, replayIndicatorPreparationFraction } from "./replayIndicatorProgress.js";
import { ReplayTapeHistoryProvider } from "./replayTapeHistoryProvider.js";
import type { ReplayTapeProjection } from "./replayTapeProjection.js";
import { TAPE_VIEWER_COMMIT } from "./replayTapeViewer.js";
import { replayHistoryRetryDelay } from "./replayHistoryRetry.js";

export const CANONICAL_HISTORY_REFRESH = "replay-canonical-history-refresh";
const BUILTINS = new Set(["MA", "EMA", "RSI", "ATR", "MACD", "BOLL", "VOL"]);
const aborted = () => new DOMException("replay indicator source changed", "AbortError");
const record = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new TypeError("invalid canonical indicator response");
  return v as Record<string, unknown>;
};
const digest = (v: unknown): ReplayDigest => {
  if (typeof v !== "string" || !/^sha256:[0-9a-f]{64}$/.test(v)) throw new TypeError("invalid canonical history epoch");
  return v as ReplayDigest;
};

export interface ReplayCanonicalBinding {
  sessionId: string;
  trackId: string;
  dataEpoch: ReplayDigest;
  revealedBoundaryMs: number;
  sourceSequence?: number;
  historyEpoch?: ReplayDigest;
  /** Metadata captured with a playback sample, never read from its newer tail. */
  sourceBars?: readonly KlineBar[];
  identity: ReplayHistoryIdentity;
  forceInitialRefresh?: boolean;
}
export interface ReplayIndicatorPreparation {
  active: number;
  phase: "history" | "prefix" | null;
  prepared: number | null;
  target: number | null;
  fraction?: number | null;
  pendingIds?: readonly string[];
}

/** The same OHLCV can belong to a newer tape cohort or metadata snapshot. */
export function replayIndicatorCalculationKey(scope: string, revision: number,
  sourceSequence: number, revealedBoundaryMs: number | null): string {
  return JSON.stringify([scope, revision, sourceSequence, revealedBoundaryMs]);
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); signal?.removeEventListener("abort", abort); reject(aborted()); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, ms);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}
function requestRows(job: IndicatorComputeBatchJob, store: SeriesWindowStore, sampledRows?: readonly KlineBar[]): object[] {
  const source = new Map((sampledRows ?? store.snapshot()).map(row => [Number(row.time), row]));
  return job.request.ohlcv.map(row => {
    const bar = source.get(row.time);
    if (!bar || ["open", "high", "low", "close", "volume"].some(key =>
      Number(bar[key]) !== Number(row[key as keyof typeof row]))) throw aborted();
    const timestamp = row.time * 1000;
    if (![bar.replayCloseTimeMs, bar.replayLastBaseOpenMs, bar.replayComponentCount, bar.replayExpectedComponents].every(Number.isSafeInteger)) {
      throw new TypeError("replay indicator bars have no authoritative source bounds");
    }
    return { open_time_ms: timestamp, close_time_ms: bar.replayCloseTimeMs,
      open: String(row.open), high: String(row.high), low: String(row.low), close: String(row.close), volume: String(row.volume),
      quote_volume: null, trades: null, taker_buy_base: null, taker_buy_quote: null,
      first_base_open_ms: Number.isSafeInteger(Number(bar.sourceFromTime) * 1000) ? Number(bar.sourceFromTime) * 1000 : timestamp,
      last_base_open_ms: bar.replayLastBaseOpenMs,
      component_count: bar.replayComponentCount, expected_components: bar.replayExpectedComponents,
      is_closed: row.is_closed !== false, synthetic: bar.replaySynthetic === true };
  });
}
function sameBinding(a: ReplayCanonicalBinding | null, b: ReplayCanonicalBinding): boolean {
  return a !== null && a.sessionId === b.sessionId && a.trackId === b.trackId && a.dataEpoch === b.dataEpoch
    && a.revealedBoundaryMs === b.revealedBoundaryMs && a.sourceSequence === b.sourceSequence && a.historyEpoch === b.historyEpoch
    && a.sourceBars === b.sourceBars
    && JSON.stringify(a.identity) === JSON.stringify(b.identity);
}

/** A calculation source belongs to one chart/review, never another chart's mutable window. */
export class ReplayCanonicalIndicators {
  private epoch: ReplayDigest | null = null;
  private active = 0;
  private readonly pending = new Map<string, number>();
  private refreshed = false;
  private needsRefresh = false;
  private refreshWork: { signal?: AbortSignal; promise: Promise<void> } | null = null;
  private readonly seeds = new WeakMap<IndicatorPayloadEnvelope, ReplayBuiltinSeed>();
  constructor(private readonly store: SeriesWindowStore,
    private readonly binding: () => ReplayCanonicalBinding | null,
    private readonly progress: (value: ReplayIndicatorPreparation) => void,
    private readonly fetcher: typeof fetch = fetch,
    private readonly projection = defaultReplayV2Api.displayProjectionBySession.bind(defaultReplayV2Api),
    private readonly fallback: IndicatorComputeBatchExecutor = computeIndicatorBatch) {}

  connect(): () => void {
    return this.store.subscribe(delta => {
      const binding = this.binding();
      if (binding && delta.sessionId === binding.sessionId && delta.trackId === binding.trackId
        && delta.dataEpoch === binding.dataEpoch && typeof delta.historyEpoch === "string") {
        const next = digest(delta.historyEpoch);
        if (this.epoch !== null && next !== this.epoch && delta.source !== CANONICAL_HISTORY_REFRESH) this.needsRefresh = true;
        this.epoch = next;
        if (delta.source === TAPE_VIEWER_COMMIT) { this.refreshed = true; this.needsRefresh = false; }
      }
    });
  }
  sourceKey = (): string => this.epoch ?? "uninitialized";
  seedForPayload = (payload: IndicatorPayloadEnvelope): ReplayBuiltinSeed | undefined => this.seeds.get(payload);
  private report(phase: ReplayIndicatorPreparation["phase"] = null, prepared: number | null = null, target: number | null = null,
    fraction: number | null = null) {
    this.progress({ active: this.active, phase, prepared, target, fraction: this.active === 1 ? fraction : null,
      pendingIds: [...this.pending.keys()] });
  }

  private async refresh(binding: ReplayCanonicalBinding, signal?: AbortSignal): Promise<void> {
    if (this.refreshWork && this.refreshWork.signal === signal && !signal?.aborted) return this.refreshWork.promise;
    const promise = this.reloadWindow(binding, signal);
    const work = { ...(signal ? { signal } : {}), promise };
    this.refreshWork = work;
    try { await promise; } finally { if (this.refreshWork === work) this.refreshWork = null; }
  }

  private async reloadWindow(binding: ReplayCanonicalBinding, signal?: AbortSignal): Promise<void> {
    if (binding.identity.source_kind === "AGG_TRADE") return this.reloadTapeWindow(binding, signal);
    signal?.throwIfAborted();
    const version = this.store.version;
    const existing = this.store.snapshot();
    const first = existing.at(0), last = existing.at(-1);
    if (!first || !last) throw aborted();
    const firstMs = Number(first.time) * 1000, lastMs = Number(last.time) * 1000;
    const provider = new ReplayHistoryProvider({ sessionId: binding.sessionId, trackId: binding.trackId,
      identity: binding.identity, fetcher: this.fetcher });
    const cancel = () => provider.cancel();
    signal?.addEventListener("abort", cancel, { once: true });
    const collected = new Map<number, ReplayDisplayBar>();
    const excluded: ReplayHistoryExcludedRange[] = [];
    let cursor = Number(last.replayCloseTimeMs) + 1;
    let lastPage: Awaited<ReturnType<ReplayHistoryProvider["loadBefore"]>> | null = null;
    // Context generations replace older preparation data, not the pinned
    // execution tail. The BAR source-bucket endpoint cannot reconstruct a
    // base-period or partially consumed tape candle (including equal-ms trades).
    const retainedTail = last.replayClosed === false && !replayUsesAuthoritativeSourceBucketProjection(
      binding.identity.source_kind.toLowerCase(), binding.identity.base_interval, binding.identity.display_interval,
    ) ? last : null;
    try {
      if (last.replayClosed === false) {
        cursor = lastMs;
      }
      if (last.replayClosed === false && retainedTail === null) {
        const projection = await this.projection(binding.sessionId, { trackId: binding.trackId,
          dataEpoch: binding.dataEpoch, displayInterval: binding.identity.display_interval,
          revealedBoundaryMs: binding.revealedBoundaryMs, limit: 1 }, signal);
        if (projection.session_id !== binding.sessionId || projection.track_id !== binding.trackId
          || projection.data_epoch !== binding.dataEpoch || projection.display_interval !== binding.identity.display_interval
          || projection.revealed_boundary_ms !== binding.revealedBoundaryMs) throw new TypeError("indicator projection source changed");
        for (const bar of projection.bars) if (bar.open_time_ms >= firstMs && bar.open_time_ms <= lastMs) collected.set(bar.open_time_ms, bar);
        if (!collected.has(lastMs)) throw new TypeError("canonical projection omitted the forming chart tail");
      }
      // Strictly decreasing public cursors, bounded output, and an abortable
      // provider prevent stalled pages from masquerading as a refreshed window.
      do {
        signal?.throwIfAborted();
        this.report("history", cursor, firstMs);
        const page = await provider.loadBefore({ beforeMs: cursor, revealedBoundaryMs: binding.revealedBoundaryMs,
          dataEpoch: binding.dataEpoch, limit: 1000 });
        lastPage = page;
        excluded.push(...page.excluded_ranges);
        for (const bar of page.bars) if (bar.open_time_ms >= firstMs && bar.open_time_ms <= lastMs) collected.set(bar.open_time_ms, bar);
        if (collected.size > Math.max(10_000, existing.length)) throw new RangeError("refreshed indicator window exceeds its chart budget");
        if (!page.has_more || page.next_before_ms <= firstMs) break;
        if (page.next_before_ms >= cursor) throw new TypeError("canonical history cursor did not progress");
        cursor = page.next_before_ms;
      } while (cursor > firstMs);
      signal?.throwIfAborted();
      if (!sameBinding(this.binding(), binding) || this.store.version !== version) throw aborted();
      // Page parsers validate internal continuity. Also check both window edges:
      // an empty/truncated page must not silently delete previously visible bars.
      const omissions = excluded.sort((a, b) => a.start_ms - b.start_ms);
      for (const row of existing) {
        let next = Number(row.time) * 1000;
        if (collected.has(next) || row === retainedTail || next < lastPage!.history_boundary_ms) continue;
        const end = Math.min(Number(row.replayCloseTimeMs), binding.revealedBoundaryMs);
        for (const range of omissions) {
          if (range.start_ms > next) break;
          if (range.end_ms >= next) next = range.end_ms + 1;
          if (next > end) break;
        }
        if (next <= end) throw new TypeError("canonical history omitted an undeclared chart range");
      }
      this.epoch = lastPage!.history_epoch;
      this.refreshed = true;
      this.needsRefresh = false;
      const previousByTime = new Map(existing.map(row => [Number(row.time) * 1000, row]));
      const rows: KlineBar[] = [...collected.values()].sort((a, b) => a.open_time_ms - b.open_time_ms).map(bar => ({
        ...previousByTime.get(bar.open_time_ms), ...replayDisplayBarToKline(bar),
        replayContextHistory: previousByTime.get(bar.open_time_ms)?.replayContextHistory === true,
      }));
      if (retainedTail !== null) rows.push(retainedTail);
      this.store.correctWindow(rows, { source: CANONICAL_HISTORY_REFRESH, sessionId: binding.sessionId, trackId: binding.trackId,
        dataEpoch: binding.dataEpoch, historyEpoch: this.epoch, historyBoundaryMs: lastPage!.history_boundary_ms,
        historyPolicy: lastPage!.history_policy, hasMore: lastPage!.has_more });
    } finally {
      signal?.removeEventListener("abort", cancel);
      provider.cancel();
    }
  }

  private async reloadTapeWindow(binding: ReplayCanonicalBinding, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    const version = this.store.version, existing = this.store.snapshot();
    const firstMs = Number(existing.at(0)?.time) * 1000, lastMs = Number(existing.at(-1)?.time) * 1000;
    if (!Number.isSafeInteger(firstMs) || !Number.isSafeInteger(lastMs)) throw aborted();
    const provider = new ReplayTapeHistoryProvider({ sessionId: binding.sessionId, trackId: binding.trackId,
      identity: binding.identity, sourceSequence: binding.sourceSequence, fetcher: this.fetcher });
    const cancel = () => provider.cancel();
    signal?.addEventListener("abort", cancel, { once: true });
    const collected = new Map<number, ReplayDisplayBar>(), gaps = new Set<number>();
    let page: ReplayTapeProjection | null = null, beforeMs: number | undefined;
    try {
      do {
        signal?.throwIfAborted(); this.report("history");
        if (!sameBinding(this.binding(), binding)) throw aborted();
        page = await provider.loadWindow({ revealedBoundaryMs: binding.revealedBoundaryMs, dataEpoch: binding.dataEpoch,
          limit: 500, ...(beforeMs === undefined ? {} : { beforeMs }) });
        for (const bar of page.bars) if (bar.open_time_ms >= firstMs && bar.open_time_ms <= lastMs) collected.set(bar.open_time_ms, bar);
        for (const at of page.incomplete_context_buckets) gaps.add(at);
        if (!page.has_more || page.next_before_ms! <= firstMs) break;
        if (beforeMs !== undefined && page.next_before_ms! >= beforeMs) throw new TypeError("tape refresh cursor did not progress");
        beforeMs = page.next_before_ms!;
      } while (beforeMs > firstMs);
      signal?.throwIfAborted();
      if (!sameBinding(this.binding(), binding) || this.store.version !== version) throw aborted();
      for (const row of existing) {
        const at = Number(row.time) * 1000;
        if (!collected.has(at) && !gaps.has(at) && at >= page!.history_boundary_ms) throw new TypeError("tape refresh omitted an undeclared chart bucket");
      }
      const previous = new Map(existing.map(row => [Number(row.time) * 1000, row]));
      const projectionStart = Number(existing.find(row => row.replayContextHistory !== true)?.time ?? Infinity) * 1000;
      const rows = [...collected.values()].sort((a, b) => a.open_time_ms - b.open_time_ms).map(bar => ({
        ...previous.get(bar.open_time_ms), ...replayDisplayBarToKline(bar),
        replayContextHistory: previous.get(bar.open_time_ms)?.replayContextHistory === true || bar.open_time_ms < projectionStart,
      }));
      this.epoch = page!.history_epoch; this.refreshed = true; this.needsRefresh = false;
      this.store.correctWindow(rows, { source: CANONICAL_HISTORY_REFRESH, sessionId: binding.sessionId, trackId: binding.trackId,
        dataEpoch: binding.dataEpoch, historyEpoch: this.epoch, historyBoundaryMs: page!.history_boundary_ms,
        historyPolicy: page!.history_policy, hasMore: page!.has_more });
    } finally { signal?.removeEventListener("abort", cancel); provider.cancel(); }
  }

  private async builtin(job: IndicatorComputeBatchJob, signal?: AbortSignal): Promise<IndicatorPayloadEnvelope> {
    const binding = this.binding();
    if (!binding) throw aborted();
    if (binding.historyEpoch !== undefined && !this.needsRefresh
      && (this.epoch === null || this.epoch === binding.historyEpoch)) {
      this.epoch = digest(binding.historyEpoch); this.refreshed = true;
    }
    if (job.request.exchange !== binding.identity.exchange || job.request.marketType !== binding.identity.market_type
      || job.request.symbol !== binding.identity.symbol || job.request.interval !== binding.identity.display_interval) throw aborted();
    if (this.needsRefresh || ((binding.forceInitialRefresh || binding.identity.source_kind === "AGG_TRADE") && !this.refreshed)) { await this.refresh(binding, signal); throw aborted(); }
    const bars = requestRows(job, this.store, binding.sourceBars);
    const preparation = new ReplayIndicatorProgress();
    let stalled = 0;
    while (true) {
      signal?.throwIfAborted();
      if (!sameBinding(this.binding(), binding)) throw aborted();
      // Native Window.fetch cannot be invoked with this calculation source as
      // its receiver. Keep the injected transport a plain function call.
      const fetcher = this.fetcher;
      const response = await fetcher(`${API_BASE}/replay/runs/session/${encodeURIComponent(binding.sessionId)}/indicator-compute`, {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        ...(signal ? { signal } : {}), body: JSON.stringify({ track_id: binding.trackId, display_interval: binding.identity.display_interval,
          revealed_boundary_ms: binding.revealedBoundaryMs, data_epoch: binding.dataEpoch, history_epoch: this.epoch,
          ...(binding.identity.source_kind === "AGG_TRADE" ? { source_sequence: binding.sourceSequence } : {}),
          name: job.request.name, params: job.request.params ?? {}, bars }),
      });
      const body = record(await response.json());
      signal?.throwIfAborted();
      if (!sameBinding(this.binding(), binding)) throw aborted();
      if (!response.ok) {
        const failure = record(body.error ?? body.detail);
        if (failure.code === "HISTORY_EPOCH_MISMATCH") { await this.refresh(binding, signal); throw aborted(); }
        const delay = replayHistoryRetryDelay(failure, stalled, [500, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000, 1_000]);
        if (delay !== undefined) { stalled++; this.report("history"); await wait(delay, signal); continue; }
        throw new Error(typeof failure.message === "string" ? failure.message : `Indicator history HTTP ${response.status}`);
      }
      const seed = record(body.seed), identity = record(seed.identity);
      if (body.protocol !== "replay.v3" || seed.session_id !== binding.sessionId || seed.track_id !== binding.trackId
        || seed.data_epoch !== binding.dataEpoch || Object.entries(binding.identity).some(([key, value]) => identity[key] !== value)) {
        throw new TypeError("canonical indicator response belongs to another source");
      }
      const epoch = digest(seed.history_epoch);
      if (this.epoch !== null && epoch !== this.epoch) throw new TypeError("canonical indicator history epoch changed");
      this.epoch = epoch;
      if (body.status === "preparing") {
        const progress = preparation.advance(body, job.request.ohlcv[0]!.time * 1000, binding.sourceSequence);
        stalled = 0;
        this.report(progress.phase, progress.prepared, progress.target,
          replayIndicatorPreparationFraction(seed.origin_ms, body.prepared_before_ms, body.target_before_ms));
        await wait(50, signal);
        continue;
      }
      if (body.status !== "ready") throw new TypeError("invalid canonical indicator state");
      const payload = parseIndicatorPayloadEnvelope(body.payload);
      this.seeds.set(payload, record(body.math_seed) as unknown as ReplayBuiltinSeed);
      return payload;
    }
  }

  compute: IndicatorComputeBatchExecutor = async ({ jobs, signal, onResults }) => {
    signal?.throwIfAborted();
    const batch = new AbortController();
    const cancel = () => batch.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const canonical = jobs.filter(job => job.request.mode === "builtin" && BUILTINS.has(job.request.name ?? ""));
    const others = jobs.filter(job => !canonical.includes(job));
    const captured = this.binding();
    this.active += jobs.length;
    for (const job of jobs) this.pending.set(job.clientId, (this.pending.get(job.clientId) ?? 0) + 1);
    this.report();
    const finish = (completed: IndicatorComputeBatchJob[]) => {
      for (const job of completed) {
        const remaining = (this.pending.get(job.clientId) ?? 1) - 1;
        if (remaining) this.pending.set(job.clientId, remaining); else this.pending.delete(job.clientId);
        this.active--;
      }
      this.report();
    };
    const publish = (results: Awaited<ReturnType<IndicatorComputeBatchExecutor>>["results"]) => {
      if (!batch.signal.aborted) onResults?.(results);
    };
    try {
      const fallback = (async () => {
        try {
          if (others.length && !captured) throw aborted();
          const replayContext = captured ? {
            sessionId: captured.sessionId, trackId: captured.trackId, dataEpoch: captured.dataEpoch,
            revealedBoundaryMs: captured.revealedBoundaryMs,
            ...(captured.sourceSequence === undefined ? {} : { sourceSequence: captured.sourceSequence }),
          } : undefined;
          const replayJobs = others.map(job => {
            requestRows(job, this.store, captured?.sourceBars);
            return { ...job, request: { ...job.request, ...(replayContext ? { replayContext } : {}) } };
          });
          const result = others.length ? await this.fallback({ jobs: replayJobs, signal: batch.signal }) : { ok: true, results: [] };
          if (others.length && captured && !sameBinding(this.binding(), captured)) throw aborted();
          publish(result.results);
          return result;
        }
        catch (error) { batch.abort(); throw error; }
        finally { finish(others); }
      })();
      // Attach both consumers immediately; a slow historical prefix must not
      // postpone launching an independent script request or leak its rejection.
      const settled = await Promise.allSettled([
        ...canonical.map(async job => {
          let result;
          try { result = { clientId: job.clientId, jobKey: job.jobKey, payload: await this.builtin(job, batch.signal) }; }
          catch (error) {
            if (batch.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) { batch.abort(); throw error; }
            result = { clientId: job.clientId, jobKey: job.jobKey,
              payload: parseIndicatorPayloadEnvelope({ ok: false, error: error instanceof Error ? error.message : String(error) }) };
          }
          finally { finish([job]); }
          publish([result]);
          return result;
        }), fallback,
      ]);
      const failed = settled.find(result => result.status === "rejected");
      if (failed?.status === "rejected") throw failed.reason;
      const results = settled.slice(0, canonical.length).map(result =>
        (result as PromiseFulfilledResult<{ clientId: string; jobKey: string; payload: IndicatorPayloadEnvelope }>).value);
      const otherResults = settled.at(-1) as PromiseFulfilledResult<Awaited<typeof fallback>>;
      results.push(...otherResults.value.results);
      return { ok: results.every(item => item.payload.ok === true), results };
    } finally { signal?.removeEventListener("abort", cancel); this.report(); }
  };
}
