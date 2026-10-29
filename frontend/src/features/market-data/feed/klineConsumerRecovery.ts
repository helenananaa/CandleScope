import type { SeriesDataFeed } from "./seriesDataFeed.js";
import type { KlineBar, MarketSeries } from "../marketDataTypes.js";

/** A disconnected consumer cannot prove continuity from a recent-tail reload. */
export class KlineConsumerRecovery {
  private readonly pending = new Map<string, {
    series: MarketSeries;
    times: number[];
    start: number;
    end: number;
    discoverTail: boolean;
    epoch: number;
  }>();
  private running = false;
  private readonly abort = new AbortController();

  get required(): boolean { return this.pending.size > 0; }

  requiredFor(interval: string): boolean {
    return [...this.pending.values()].some((item) => item.series.interval === interval);
  }

  capture(
    feed: SeriesDataFeed,
    series: MarketSeries,
    rows: readonly KlineBar[],
    { discoverTail = false }: { discoverTail?: boolean } = {},
  ): void {
    if (this.abort.signal.aborted) return;
    const key = feed.seriesKey(series);
    const pending = this.pending.get(key);
    const previous = pending && feed.isCurrent(series, pending.epoch) ? pending : undefined;
    const epoch = feed.beginEpoch(series); // Fence HTTP results started before the gap.
    // A forming row may finalize while disconnected and fall outside latest2.
    // Keep its timestamp even when no temporal hole remains in the window.
    const times = rows.map((row) => Number(row.time)).filter(Number.isFinite);
    if (times.length === 0 && !discoverTail && !previous) return;
    this.pending.set(key, {
      series,
      // Retain the original obligation across repeated gaps, without growing
      // a timestamp set indefinitely as navigation/streaming changes the view.
      times: previous?.times.length ? previous.times : times,
      start: Math.min(previous?.start ?? Infinity, ...times),
      end: Math.max(previous?.end ?? -Infinity, ...times),
      discoverTail: discoverTail || previous?.discoverTail === true,
      epoch,
    });
  }

  async recover(
    feed: SeriesDataFeed,
    isSubscribed: (interval: string) => boolean,
  ): Promise<Array<{ series: MarketSeries; latest: KlineBar }>> {
    const resumed: Array<{ series: MarketSeries; latest: KlineBar }> = [];
    if (this.running || this.abort.signal.aborted) return resumed;
    this.running = true;
    try {
      for (const [key, checkpoint] of this.pending) {
        // Explicit navigation/reset supersedes the old recovery demand too.
        if (!feed.isCurrent(checkpoint.series, checkpoint.epoch)) {
          this.pending.delete(key);
          continue;
        }
        if (!isSubscribed(checkpoint.series.interval)) continue;
        try {
          let start = checkpoint.start;
          let end = checkpoint.end;
          if (checkpoint.discoverTail) {
            // Discovery is not recovery proof and must not publish a partial
            // tail before the suspended range has been verified.
            const latest = await feed.getLatest(checkpoint.series, {
              limit: 2, source: "consumer-resume-tail", commit: "none", signal: this.abort.signal,
            });
            if (this.pending.get(key) !== checkpoint || latest.stale || !latest.data.length) continue;
            const latestTime = Number(latest.data.at(-1)?.time);
            if (!Number.isFinite(latestTime) || latestTime < end) continue;
            start = Math.min(start, Number(latest.data[0]?.time));
            end = latestTime;
          }
          const result = await feed.getRange(checkpoint.series, {
            startSec: start,
            endSec: end,
            source: "consumer-resync", strict: true, maxPages: 20,
            signal: this.abort.signal,
          });
          const times = new Set(result.data.map((row) => Number(row.time)));
          if (this.pending.get(key) === checkpoint
            && !result.stale && result.complete === true && result.verified_contiguous === true
            && result.retryable === false && result.truncated === false
            && Array.isArray(result.missing_ranges) && result.missing_ranges.length === 0
            && times.has(start) && times.has(end)
            && checkpoint.times.every((time) => times.has(time))) {
            this.pending.delete(key);
            const latest = result.data.at(-1);
            if (checkpoint.discoverTail && latest) resumed.push({ series: checkpoint.series, latest });
          }
        } catch {
          // Keep the explicit recovery state. The owner retries with backoff.
        }
      }
    } finally {
      this.running = false;
    }
    return resumed;
  }

  close(): void {
    this.abort.abort();
    this.pending.clear();
  }
}
