import { API_BASE } from "../../services/apiConfig.js";
import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { parsePage, ReplayHistoryProvider, ReplayHistoryProtocolError,
  type ReplayHistoryProviderOptions, type ReplayHistoryRequest, type ReplayHistoryPage,
  type ReplayHistorySource, type ReplayHistoryExcludedRange } from "./replayHistoryProvider.js";
import { loadReplayTapeProjection, type ReplayTapeProjection } from "./replayTapeProjection.js";
import { replayDisplayBarToKline } from "./replaySeriesProjection.js";
import { ReplayV2ApiClient } from "./replayV2Api.js";
import type { ReplayDigest } from "./replayTypes.js";

type Options = ReplayHistoryProviderOptions & { sourceSequence?: number | (() => number | null) | undefined };
export type ReplayTapeWindowRequest = Omit<ReplayHistoryRequest, "beforeMs"> & { beforeMs?: number };

export function createReplayHistoryProvider(options: Options): ReplayHistorySource {
  return options.identity.source_kind === "AGG_TRADE" ? new ReplayTapeHistoryProvider(options) : new ReplayHistoryProvider(options);
}

/** Closed history and display windows share one generation and selected tape. */
export class ReplayTapeHistoryProvider implements ReplayHistorySource {
  readonly sessionId: string;
  readonly trackId: string;
  readonly identity: Options["identity"];
  private readonly api: ReplayV2ApiClient;
  private readonly inflight = new Map<string, { controller: AbortController; promise: Promise<ReplayTapeProjection> }>();
  private epoch: ReplayDigest | null = null;
  private generation = 0;
  constructor(private readonly options: Options) {
    this.sessionId = options.sessionId; this.trackId = options.trackId; this.identity = options.identity;
    if (this.identity.source_kind !== "AGG_TRADE" || options.sourceSequence === undefined) {
      throw new TypeError("tape history requires its selected source sequence");
    }
    if (options.pendingRetryDelaysMs && (options.pendingRetryDelaysMs.length > 20
      || options.pendingRetryDelaysMs.some(delay => !Number.isFinite(delay) || delay < 0 || delay > 30_000))) {
      throw new TypeError("invalid tape download retry delays");
    }
    this.api = new ReplayV2ApiClient({ ...(options.fetcher ? { fetcher: options.fetcher } : {}),
      basePath: options.apiBase === undefined ? `${API_BASE}/replay` : `${options.apiBase.replace(/\/$/, "")}/api/v1/replay` });
  }
  get historyEpoch(): ReplayDigest | null { return this.epoch; }
  private sequence(): number {
    const sequence = typeof this.options.sourceSequence === "function" ? this.options.sourceSequence() : this.options.sourceSequence;
    if (typeof sequence !== "number" || !Number.isSafeInteger(sequence) || sequence < 0) throw new TypeError("tape source sequence is unavailable");
    return sequence;
  }
  adoptEpoch(epoch: ReplayDigest): void {
    if (!/^sha256:[0-9a-f]{64}$/.test(epoch)) throw new TypeError("invalid tape history epoch");
    if (epoch === this.epoch) return;
    this.cancel(); this.epoch = epoch;
  }
  loadWindow(request: ReplayTapeWindowRequest, acceptAdvancedSource = false): Promise<ReplayTapeProjection> {
    const sourceSequence = this.sequence(), generation = this.generation, expectedEpoch = this.epoch;
    const key = JSON.stringify([request, sourceSequence, expectedEpoch, acceptAdvancedSource]);
    const previous = this.inflight.get(key);
    if (previous) return previous.promise;
    const controller = new AbortController();
    const promise = (async () => {
      const result = await loadReplayTapeProjection(signal => this.api.tapeProjectionBySession(this.sessionId, {
        trackId: this.trackId, displayInterval: this.identity.display_interval, sourceSequence,
        dataEpoch: request.dataEpoch, revealedBoundaryMs: request.revealedBoundaryMs,
        limit: Math.min(500, request.limit ?? 500),
        ...(request.beforeMs === undefined ? {} : { beforeMs: request.beforeMs }),
        ...(expectedEpoch === null ? {} : { historyEpoch: expectedEpoch }),
      }, signal), controller.signal, undefined,
      this.options.pendingRetryDelaysMs === undefined ? {} : { pendingRetryDelaysMs: this.options.pendingRetryDelaysMs });
      if (controller.signal.aborted || generation !== this.generation
        || (acceptAdvancedSource ? this.sequence() < sourceSequence : sourceSequence !== this.sequence())) {
        throw new DOMException("tape history source changed", "AbortError");
      }
      if (Object.entries(this.identity).some(([name, value]) => result.identity[name as keyof typeof result.identity] !== value)
        || (this.epoch !== null && result.history_epoch !== this.epoch)) throw new TypeError("tape history source changed");
      this.epoch = result.history_epoch;
      return result;
    })().finally(() => { if (this.inflight.get(key)?.promise === promise) this.inflight.delete(key); });
    this.inflight.set(key, { controller, promise });
    return promise;
  }
  async loadBefore(input: ReplayHistoryRequest): Promise<ReplayHistoryPage> {
    const request = { ...input, limit: Math.min(500, input.limit ?? 500) };
    const result = await this.loadWindow(request, true);
    const bars = result.bars.filter(bar => bar.is_closed);
    const buckets = new Set(result.incomplete_context_buckets);
    for (const bar of result.bars) if (!bar.is_closed) {
      const partialOrigin = bar.open_time_ms === result.history_boundary_ms && bar.component_count < bar.expected_components;
      if (!partialOrigin && !buckets.has(bar.open_time_ms)) {
        throw new ReplayHistoryProtocolError("history bucket is not closed by its selected tape sequence");
      }
      buckets.add(bar.open_time_ms);
    }
    const timeline = createIntervalTimeline(this.identity.display_interval)!;
    const excluded: ReplayHistoryExcludedRange[] = [...buckets].sort((a, b) => a - b).map(at => ({
      start_ms: at, end_ms: Number(timeline.next(at / 1000)) * 1000 - 1,
      reason: "source_gap_affected_display_bucket", source_reason: "incomplete_tape_context",
    }));
    return parsePage({ protocol: "replay.v3", schema_version: "replay.history.v3", run_id: result.run_id,
      session_id: result.session_id, track_id: result.track_id, identity: result.identity, data_epoch: result.data_epoch,
      history_epoch: result.history_epoch, history_boundary_ms: result.history_boundary_ms, history_policy: result.history_policy,
      revealed_boundary_ms: result.revealed_boundary_ms, bars, excluded_ranges: excluded,
      next_before_ms: bars[0]?.open_time_ms ?? result.next_before_ms, has_more: result.has_more }, {
      sessionId: this.sessionId, trackId: this.trackId, identity: this.identity, request, expectedHistoryEpoch: this.epoch,
    });
  }
  cancel(): void {
    this.generation++;
    for (const pending of this.inflight.values()) pending.controller.abort();
    this.inflight.clear(); this.epoch = null;
  }
}

export function applyReplayTapeWindow(store: SeriesWindowStore, page: ReplayTapeProjection, replace = false): void {
  if (page.status !== "ready") throw new ReplayHistoryProtocolError("tape page is still preparing");
  const rows = page.bars.map(replayDisplayBarToKline);
  const metadata = { source: "replay-tape-window", sessionId: page.session_id, trackId: page.track_id,
    dataEpoch: page.data_epoch, historyEpoch: page.history_epoch, historyBoundaryMs: page.history_boundary_ms,
    historyPolicy: page.history_policy, hasMore: page.has_more };
  if (replace) store.replace(rows, metadata);
  else store.applyRange(rows, metadata);
}
