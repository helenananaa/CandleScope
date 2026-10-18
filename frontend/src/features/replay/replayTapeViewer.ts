import { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { parseIntervalSeconds } from "../../utils/intervals.js";
import type { ReplayHistoryIdentity, ReplayHistoryPolicy } from "./replayHistoryProvider.js";
import { ReplayTapeHistoryProvider } from "./replayTapeHistoryProvider.js";
import type { ReplayTapeProjection } from "./replayTapeProjection.js";
import { replayDisplayBarToKline } from "./replaySeriesProjection.js";
import { buildReplayViewerSeriesKey } from "./replayViewerProjection.js";
import type { ReplayDigest } from "./replayTypes.js";

export const TAPE_VIEWER_COMMIT = "replay-viewer-tape-projection";
export interface ReplayTapeViewerAuthority {
  generation: number;
  sourceSequence: number;
  virtualTimeMs: number;
}
export interface ReplayTapeViewerObservation extends ReplayTapeViewerAuthority {
  historyEpoch: ReplayDigest;
  historyBoundaryMs: number;
  historyPolicy: ReplayHistoryPolicy;
  hasMore: boolean;
}
interface Options {
  sessionId: string;
  trackId: string;
  dataEpoch: ReplayDigest;
  identity: ReplayHistoryIdentity;
  target: SeriesWindowStore;
  source: SeriesWindowStore;
  authority: () => ReplayTapeViewerAuthority | null;
  observation: (value: ReplayTapeViewerObservation | null) => void;
  loading: (value: boolean) => void;
  error: (value: Error | null) => void;
  fetcher?: typeof fetch;
  apiBase?: string;
}
const same = (a: ReplayTapeViewerAuthority | null, b: ReplayTapeViewerAuthority) => a !== null
  && a.generation === b.generation && a.sourceSequence === b.sourceSequence && a.virtualTimeMs === b.virtualTimeMs;
const forward = (a: ReplayTapeViewerAuthority, b: ReplayTapeViewerAuthority) => a.generation === b.generation
  && a.sourceSequence >= b.sourceSequence && a.virtualTimeMs >= b.virtualTimeMs;

/** A display observer finishes one selected tape prefix while newer ticks queue.
 * Its committed boundary, rather than the broker's newer clock, owns indicators.
 * Rewinds and disposal cancel it; forward playback cannot starve preparation.
 */
export class ReplayTapeViewer {
  private seen: ReplayTapeViewerAuthority | null = null;
  private shown: ReplayTapeViewerObservation | null = null;
  private provider: ReplayTapeHistoryProvider | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private version = 0;
  private stopped = false;
  private failed = false;
  private forced = false;
  private startedAt = -Infinity;
  private waiters: ((ok: boolean) => void)[] = [];
  constructor(private readonly options: Options) {
    // A newly bound observer has not proved that any retained target rows
    // belong to its selected prefix (including during reconnect/rewind).
    options.target.clear({ source: TAPE_VIEWER_COMMIT });
  }

  update = (): void => {
    if (this.stopped) return;
    const current = this.options.authority();
    if (current === null) {
      if (this.seen !== null) {
        this.version++; this.provider?.cancel(); this.provider = null;
        if (this.timer) clearTimeout(this.timer); this.timer = null;
        this.seen = null; this.shown = null; this.failed = false; this.forced = false;
        this.options.target.clear({ source: TAPE_VIEWER_COMMIT });
        this.options.observation(null); this.options.loading(false); this.settle(false);
      }
      return;
    }
    if (this.seen !== null && !forward(current, this.seen)) {
      this.version++; this.provider?.cancel(); this.provider = null;
      if (this.timer) clearTimeout(this.timer); this.timer = null;
      this.shown = null; this.failed = false; this.forced = false; this.settle(false);
      this.options.target.clear({ source: TAPE_VIEWER_COMMIT });
      this.options.observation(null);
    }
    this.seen = current;
    if (this.provider || this.timer || this.failed || (!this.forced && (same(this.shown, current) || this.options.target.rightTruncated))) return;
    const delay = Math.max(0, 100 - (performance.now() - this.startedAt));
    if (delay) this.timer = setTimeout(() => { this.timer = null; this.update(); }, delay);
    else void this.load(current);
  };

  restoreLatest = (): Promise<boolean> => {
    if (this.stopped || this.options.authority() === null) return Promise.resolve(false);
    this.version++; this.provider?.cancel(); this.provider = null;
    if (this.timer) clearTimeout(this.timer); this.timer = null;
    this.failed = false; this.forced = true;
    const result = new Promise<boolean>(resolve => { this.waiters.push(resolve); });
    this.update(); return result;
  };

  private settle(ok: boolean) { for (const waiter of this.waiters.splice(0)) waiter(ok); }

  private async load(selected: ReplayTapeViewerAuthority): Promise<void> {
    const { options } = this, token = this.version;
    const provider = new ReplayTapeHistoryProvider({ sessionId: options.sessionId, trackId: options.trackId,
      identity: options.identity, sourceSequence: selected.sourceSequence,
      ...(options.fetcher ? { fetcher: options.fetcher } : {}), ...(options.apiBase === undefined ? {} : { apiBase: options.apiBase }) });
    this.provider = provider; this.startedAt = performance.now();
    options.loading(true); options.error(null);
    try {
      // Publish a useful first viewport before preparing a full history page.
      // Viewport/warmup demand still pages left, and explicit restoration keeps
      // its full window. This does not shorten the canonical indicator prefix.
      const limit = this.shown === null && !this.forced ? 128 : 500;
      let page = await provider.loadWindow({ dataEpoch: options.dataEpoch, revealedBoundaryMs: selected.virtualTimeMs, limit });
      const newest = page, previousLast = options.target.last();
      let incoming = [...page.bars], pages = 1;
      // A large jump can outgrow one page. Fill the seam to the prior display
      // within the chart's retention budget instead of inventing a blank gap.
      while (!this.forced && previousLast && this.shown?.historyEpoch === page.history_epoch && page.has_more
        && page.next_before_ms! > Number(previousLast.time) * 1000 && incoming.length < options.target.maxBars
        && pages < Math.ceil(options.target.maxBars / 500)) {
        page = await provider.loadWindow({ dataEpoch: options.dataEpoch, revealedBoundaryMs: selected.virtualTimeMs,
          beforeMs: page.next_before_ms!, limit: Math.min(500, options.target.maxBars - incoming.length) });
        incoming = [...page.bars, ...incoming];
        pages++;
      }
      const current = options.authority();
      if (this.stopped || token !== this.version || current === null || !forward(current, selected)) return;
      if (options.target.rightTruncated && !this.forced) return;
      this.commit({ ...newest, bars: incoming, has_more: page.has_more, next_before_ms: page.next_before_ms }, selected, this.forced);
      this.forced = false; this.settle(true);
    } catch (cause) {
      if (!this.stopped && token === this.version && !(cause instanceof DOMException && cause.name === "AbortError")) {
        this.failed = true;
        options.error(cause instanceof Error ? cause : new Error(String(cause)));
        this.settle(false);
      }
    } finally {
      provider.cancel();
      if (this.provider === provider) {
        this.provider = null;
        options.loading(false);
        this.update();
      }
    }
  }

  private commit(page: ReplayTapeProjection, selected: ReplayTapeViewerAuthority, force: boolean) {
    const { target, source, identity } = this.options;
    const next = page.bars.map(replayDisplayBarToKline), previous = target.snapshot(), last = previous.at(-1);
    const metadata = { source: TAPE_VIEWER_COMMIT, sessionId: page.session_id, trackId: page.track_id,
      dataEpoch: page.data_epoch, historyEpoch: page.history_epoch, historyBoundaryMs: page.history_boundary_ms,
      historyPolicy: page.history_policy, hasMore: page.has_more, publicTimeMs: selected.virtualTimeMs,
      sourceSequence: selected.sourceSequence, serverAuthoritative: true,
      historyWindowReset: force || this.shown?.historyEpoch !== page.history_epoch };
    target.intervalSeconds = parseIntervalSeconds(identity.display_interval);
    target.seriesKey = buildReplayViewerSeriesKey(source, identity.display_interval);
    const overlap = last && next.some(row => row.time === last.time);
    if (!force && this.shown?.historyEpoch === page.history_epoch && overlap) {
      // All earlier displayed closed rows are immutable under this epoch.
      // Preserve user-loaded history; publish the forming tail and additions
      // with normal tick/append semantics rather than replacing every frame.
      const tail = next.find(row => row.time === last.time)!;
      target.applyTick(tail, metadata);
      const appended = next.filter(row => row.time > last.time);
      if (appended.length) target.applyRange(appended, metadata);
    } else {
      const bounded = next.slice(-target.maxBars);
      const withinCurrent = previous.length > 0 && bounded.every(row => row.time >= previous[0]!.time && row.time <= last!.time);
      if (!force && this.shown?.historyEpoch === page.history_epoch && withinCurrent && !target.rightTruncated) target.correctWindow(bounded, metadata);
      else target.replace(bounded, metadata);
    }
    this.shown = { ...selected, historyEpoch: page.history_epoch,
      historyBoundaryMs: page.history_boundary_ms, historyPolicy: page.history_policy, hasMore: page.has_more === true };
    this.options.observation(this.shown);
  }

  dispose(): void {
    this.stopped = true; this.version++; this.provider?.cancel(); this.provider = null;
    if (this.timer) clearTimeout(this.timer); this.timer = null;
    this.settle(false);
  }
}
