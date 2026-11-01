import { hasVerifiedRangeCoverage, recoveryRetryDecision } from "../quality/klineQualityPolicy.js";
import type { SeriesDataFeed } from "./seriesDataFeed.js";
import type { KlineBar, MarketSeries } from "../marketDataTypes.js";
import { nextIntervalTime, previousIntervalTime } from "../../../utils/intervalTimeline.js";
import { parseMarketVersion, sameStream } from "../manager/marketHealth.js";

/** A disconnected consumer cannot prove continuity from a recent-tail reload. */
export class KlineConsumerRecovery {
  private readonly pending = new Map<string, {
    series: MarketSeries;
    times: number[];
    start: number;
    end: number;
    formingEnd: number | null;
    discoverTail: boolean;
    epoch: number;
    retryAt?: number;
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
    const end = Math.max(previous?.end ?? -Infinity, ...times);
    const endRows = rows.filter((row) => Number(row.time) === end);
    const formingEnd = endRows.length && endRows.every((row) => row.is_closed === false)
      && !(previous?.end === end && previous.formingEnd !== end) ? end
      : !endRows.length && previous?.formingEnd === end ? end : null;
    this.pending.set(key, {
      series,
      // Retain the original obligation across repeated gaps, without growing
      // a timestamp set indefinitely as navigation/streaming changes the view.
      times: previous?.times.length ? previous.times : times,
      start: Math.min(previous?.start ?? Infinity, ...times),
      end,
      formingEnd,
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
        if (!isSubscribed(checkpoint.series.interval) || Date.now() < (checkpoint.retryAt ?? 0)) continue;
        try {
          let start = checkpoint.start;
          let end = checkpoint.end;
          let formingEnd = checkpoint.formingEnd;
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
            if (end > checkpoint.end) formingEnd = latest.data.at(-1)?.is_closed === false ? end : null;
          }
          // Range endpoints contain closed rows only. A forming-only window
          // needs its preceding closed bucket as an independent proof anchor.
          if (start === end && formingEnd === end) {
            start = previousIntervalTime(checkpoint.series.interval, end) ?? start;
          }
          const result = await feed.getRange(checkpoint.series, {
            startSec: start,
            endSec: end,
            source: "consumer-resync", strict: true, maxPages: 20,
            signal: this.abort.signal,
          });
          const times = new Set(result.data.map((row) => Number(row.time)));
          let latest = result.data.at(-1);
          if (this.pending.get(key) === checkpoint && !result.stale && hasVerifiedRangeCoverage(result)
            && !times.has(end) && formingEnd === end && times.has(start)
            && checkpoint.times.every((time) => time === end || times.has(time))
            && result.reached_latest_closed_bar === true && result.all_rows_final === true
            && typeof result.effective_end_ms === "number" && Number.isSafeInteger(result.effective_end_ms)
            && result.query_end_ms === result.effective_end_ms
            && times.has(result.effective_end_ms / 1000)
            && nextIntervalTime(checkpoint.series.interval, result.effective_end_ms / 1000) === end) {
            const closedVersion = parseMarketVersion(result.stream_version, checkpoint.series);
            if (closedVersion?.stable === true) {
              const tail = await feed.getLatest(checkpoint.series, {
                limit: 2, source: "consumer-resync-forming", commit: "none", signal: this.abort.signal,
              });
              const tailVersion = parseMarketVersion(tail.stream_version, checkpoint.series);
              const row = tail.data.at(-1);
              // A correction or a new closed bucket invalidates the combined
              // proof; retry the strict range instead of reopening a final row.
              if (this.pending.get(key) === checkpoint && feed.isCurrent(checkpoint.series, checkpoint.epoch)
                && !tail.stale && row?.is_closed === false && Number(row.time) === end
                && tailVersion?.stable === true && sameStream(closedVersion, tailVersion)
                && tailVersion.barrier === closedVersion.barrier && tailVersion.sequence >= closedVersion.sequence
                && closedVersion.observed_at_ms > 0 && tailVersion.observed_at_ms >= closedVersion.observed_at_ms) {
                feed.applyResult(checkpoint.series, { ...tail, data: [row] }, {
                  epoch: checkpoint.epoch, source: "consumer-resync-forming", mode: "tick", commit: "patch-active",
                });
                times.add(end);
                latest = row;
              }
            }
          }
          if (this.pending.get(key) === checkpoint
            && !result.stale && hasVerifiedRangeCoverage(result)
            && times.has(start) && times.has(end)
            && checkpoint.times.every((time) => times.has(time))) {
            this.pending.delete(key);
            if (checkpoint.discoverTail && latest) resumed.push({ series: checkpoint.series, latest });
          } else if (this.pending.get(key) === checkpoint && !result.stale) {
            const decision = recoveryRetryDecision(result, Date.now());
            if (decision) checkpoint.retryAt = decision.retryAt;
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

  observeAvailability(): void {
    // A backfill notification is permission to re-read, never recovery proof.
    for (const checkpoint of this.pending.values()) {
      if (checkpoint.retryAt !== undefined) checkpoint.retryAt = 0;
    }
  }

  close(): void {
    this.abort.abort();
    this.pending.clear();
  }
}
