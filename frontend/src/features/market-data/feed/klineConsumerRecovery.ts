import type { SeriesDataFeed } from "./seriesDataFeed.js";
import type { KlineBar, MarketSeries } from "../marketDataTypes.js";

/** A disconnected consumer cannot prove continuity from a recent-tail reload. */
export class KlineConsumerRecovery {
  private readonly pending = new Map<string, {
    series: MarketSeries;
    times: number[];
  }>();
  private running = false;

  get required(): boolean { return this.pending.size > 0; }

  requiredFor(interval: string): boolean {
    return [...this.pending.values()].some((item) => item.series.interval === interval);
  }

  capture(feed: SeriesDataFeed, series: MarketSeries, rows: readonly KlineBar[]): void {
    feed.beginEpoch(series); // Fence HTTP results started before the gap.
    const times = rows.filter((row) => row.is_closed !== false).map((row) => Number(row.time));
    if (times.length === 0) return;
    this.pending.set(feed.seriesKey(series), { series, times });
  }

  async recover(feed: SeriesDataFeed, isSubscribed: (interval: string) => boolean): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      for (const [key, checkpoint] of this.pending) {
        if (!isSubscribed(checkpoint.series.interval)) continue;
        try {
          const result = await feed.getRange(checkpoint.series, {
            startSec: checkpoint.times.reduce((a, b) => Math.min(a, b), Infinity),
            endSec: checkpoint.times.reduce((a, b) => Math.max(a, b), -Infinity),
            source: "consumer-resync", strict: true, maxPages: 20,
          });
          const times = new Set(result.data.map((row) => Number(row.time)));
          if (this.pending.get(key) === checkpoint
            && !result.stale && result.complete === true && result.verified_contiguous === true
            && result.retryable === false && result.truncated === false
            && Array.isArray(result.missing_ranges) && result.missing_ranges.length === 0
            && checkpoint.times.every((time) => times.has(time))) {
            this.pending.delete(key);
          }
        } catch {
          // Keep the explicit recovery state. The owner retries with backoff.
        }
      }
    } finally {
      this.running = false;
    }
  }
}
