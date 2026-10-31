import type { MarketSeries } from "../market-data/marketDataTypes.js";
import type { MarketCacheChange, SharedMarketCache } from "../market-data/manager/sharedMarketCache.js";
import type { StableSeriesSnapshot } from "../market-data/window/stableSeriesSnapshot.js";

export interface IndicatorInputRange { readonly from: number; readonly to: number }

/** Workspace-owned range leases over immutable market facts. This is an input
 * adapter, not another row cache; each consumer releases only its own lease. */
export class IndicatorInputRanges {
  private readonly releases = new Set<() => void>();
  private disposed = false;
  constructor(private readonly cache: SharedMarketCache) {}

  read(series: MarketSeries, range: IndicatorInputRange): StableSeriesSnapshot {
    this.assertRange(range);
    series = { ...series };
    range = { ...range };
    const snapshot = this.cache.read(series, range);
    const stamp = this.cache.captureVersion(series, range);
    const last = snapshot.rows.at(-1);
    const closed = this.cache.captureVersion(series, { from: range.from,
      to: last?.is_closed === false ? Number(last.time) - 1 : range.to });
    return Object.freeze({ state: undefined, version: snapshot.version, rows: snapshot.rows,
      isCurrent: (policy = "exact") => {
        if (this.disposed) return false;
        if (policy !== "forming-preview" || last?.is_closed !== false) return stamp.isCurrent() && snapshot.isCurrent();
        if (!closed.isCurrent()) return false;
        const current = this.cache.read(series, range).rows;
        return current.length === snapshot.rows.length && current.at(-1)?.time === last.time
          && current.at(-1)?.is_closed === false
          && snapshot.rows.slice(0, -1).every((row, i) => row === current[i]);
      },
    });
  }

  subscribe(series: MarketSeries, range: IndicatorInputRange, onChange: (change: MarketCacheChange) => void): () => void {
    this.assertRange(range);
    if (this.disposed) throw new Error("Indicator inputs disposed");
    const owned = { ...range };
    const retention = this.cache.retain(series, owned);
    const unsubscribe = this.cache.subscribe(series, change => {
      if (this.releases.has(release) && (!change.rows.length
        || change.rows.some(row => Number(row.time) >= owned.from && Number(row.time) <= owned.to))) onChange(change);
    });
    const release = () => { unsubscribe(); retention.release(); this.releases.delete(release); };
    this.releases.add(release);
    return release;
  }

  diagnostics() { return { subscriptions: this.releases.size }; }
  dispose(): void { this.disposed = true; for (const release of this.releases) release(); }
  private assertRange(range: IndicatorInputRange): void {
    if (!Number.isFinite(range.from) || !Number.isFinite(range.to) || range.from > range.to) throw new Error("Explicit indicator input range required");
  }
}
