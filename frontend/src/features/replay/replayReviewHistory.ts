import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { CANONICAL_HISTORY_REFRESH } from "./replayCanonicalIndicators.js";
import { applyReplayHistoryPage, type ReplayHistorySource } from "./replayHistoryProvider.js";
import { applyReplayTapeWindow, ReplayTapeHistoryProvider } from "./replayTapeHistoryProvider.js";
import { commitReplayReviewPrefix, loadReplayReviewPrefix, REVIEW_INITIAL_BARS, REVIEW_PREFIX_MAX_BARS } from "./replayReviewPrefix.js";
import { replayDisplayBarToKline } from "./replaySeriesProjection.js";
import type { ReplayDigest } from "./replayTypes.js";
import { defaultReplayV2Api } from "./replayV2Api.js";
import { replayUsesAuthoritativeSourceBucketProjection } from "./replayViewerProjection.js";
import { intervalsSemanticallyEquivalent } from "../../utils/intervals.js";

export interface ReplayReviewHistoryState {
  loading: boolean;
  hasMore: boolean;
  bounded: boolean;
  error: string | null;
}

/** One selected review event owns its cursor, pending requests and chart window. */
export class ReplayReviewHistory {
  private readonly abort = new AbortController();
  private nextBeforeMs: number;
  private more: Promise<void> | null = null;
  private unsubscribe: (() => void) | null = null;
  private initialized = false;
  private state: ReplayReviewHistoryState = { loading: false, hasMore: false, bounded: false, error: null };

  constructor(private readonly target: SeriesWindowStore, private readonly provider: ReplayHistorySource,
    private readonly dataEpoch: ReplayDigest, private readonly revealedBoundaryMs: number,
    private readonly report: (state: ReplayReviewHistoryState) => void,
    private readonly projection = defaultReplayV2Api.displayProjectionBySession.bind(defaultReplayV2Api)) {
    this.nextBeforeMs = Math.min(Number.MAX_SAFE_INTEGER, revealedBoundaryMs + 1);
  }

  private update(value: Partial<ReplayReviewHistoryState>) {
    this.state = { ...this.state, ...value };
    if (!this.abort.signal.aborted) this.report(this.state);
  }

  async initialize(datasetKey: string): Promise<void> {
    this.abort.signal.throwIfAborted();
    const { provider, revealedBoundaryMs, dataEpoch } = this;
    if (!(provider instanceof ReplayTapeHistoryProvider) && provider.identity.source_kind === "AGG_TRADE"
      && !intervalsSemanticallyEquivalent(provider.identity.base_interval, provider.identity.display_interval)) {
      throw new TypeError("coarse tape review requires a sequence-bound tail projection");
    }
    const prefix = await (async () => {
      if (!(provider instanceof ReplayTapeHistoryProvider)) return loadReplayReviewPrefix(provider, dataEpoch, revealedBoundaryMs, this.abort.signal);
      const page = await provider.loadWindow({ dataEpoch, revealedBoundaryMs, limit: REVIEW_INITIAL_BARS });
      const source = new SeriesWindowStore({ maxBars: REVIEW_PREFIX_MAX_BARS });
      applyReplayTapeWindow(source, page, true);
      return { source, nextBeforeMs: page.next_before_ms!, hasMore: page.has_more!, bounded: false };
    })();
    const identity = provider.identity;
    if (replayUsesAuthoritativeSourceBucketProjection(identity.source_kind.toLowerCase(), identity.base_interval, identity.display_interval)) {
      const tail = await this.projection(provider.sessionId, { trackId: provider.trackId, dataEpoch,
        displayInterval: identity.display_interval, revealedBoundaryMs, limit: 1 }, this.abort.signal);
      if (tail.session_id !== provider.sessionId || tail.track_id !== provider.trackId || tail.data_epoch !== dataEpoch
        || tail.display_interval !== identity.display_interval || tail.revealed_boundary_ms !== revealedBoundaryMs) {
        throw new TypeError("review projection source changed");
      }
      prefix.source.applyRange(tail.bars.map(replayDisplayBarToKline));
    }
    this.abort.signal.throwIfAborted();
    commitReplayReviewPrefix(this.target, prefix.source, identity.display_interval, datasetKey);
    this.nextBeforeMs = prefix.nextBeforeMs;
    this.initialized = true;
    this.unsubscribe = this.target.subscribe(delta => {
      if (delta.source === CANONICAL_HISTORY_REFRESH && delta.sessionId === provider.sessionId
        && delta.trackId === provider.trackId && delta.dataEpoch === dataEpoch && typeof delta.historyEpoch === "string") {
        provider.adoptEpoch(delta.historyEpoch as ReplayDigest);
        this.nextBeforeMs = Number(this.target.first()?.time ?? this.nextBeforeMs / 1000) * 1000;
        const hasMore = typeof delta.hasMore === "boolean" ? delta.hasMore : this.state.hasMore;
        this.update({ hasMore, bounded: hasMore && this.target.barCount >= REVIEW_PREFIX_MAX_BARS });
      }
    });
    this.update({ hasMore: prefix.hasMore, bounded: prefix.bounded });
  }

  loadMoreLeft = (): Promise<void> => {
    if (this.more) return this.more;
    if (!this.initialized || this.abort.signal.aborted || !this.state.hasMore || this.state.bounded) return Promise.resolve();
    const remaining = REVIEW_PREFIX_MAX_BARS - this.target.barCount;
    if (remaining <= 0) { this.update({ bounded: true }); return Promise.resolve(); }
    this.update({ loading: true, error: null });
    const beforeMs = this.nextBeforeMs;
    const work = (async () => {
      try {
        const request = { beforeMs, dataEpoch: this.dataEpoch,
          revealedBoundaryMs: this.revealedBoundaryMs, limit: Math.min(REVIEW_INITIAL_BARS, remaining) };
        const page = this.provider instanceof ReplayTapeHistoryProvider
          ? await this.provider.loadWindow(request) : await this.provider.loadBefore(request);
        this.abort.signal.throwIfAborted();
        if (page.has_more && page.next_before_ms! >= beforeMs) throw new TypeError("review history cursor did not progress");
        if (page.schema_version === "replay.tape-projection.v1") applyReplayTapeWindow(this.target, page);
        else applyReplayHistoryPage(this.target, page, { expectedBeforeMs: beforeMs });
        this.nextBeforeMs = page.next_before_ms!;
        this.update({ hasMore: page.has_more!, bounded: page.has_more! && this.target.barCount >= REVIEW_PREFIX_MAX_BARS });
      } catch (error) {
        if (!this.abort.signal.aborted && !(error instanceof DOMException && error.name === "AbortError")) {
          this.update({ error: error instanceof Error ? error.message : String(error) });
        }
      } finally { this.more = null; this.update({ loading: false }); }
    })();
    this.more = work;
    return work;
  };

  cancel(): void { this.abort.abort(); this.provider.cancel(); this.unsubscribe?.(); this.unsubscribe = null; }
}
