import type { WarmReason } from "./marketWarmQueue.js";
import type { KlineStreamController, KlineStreamFactory } from "../klineContracts.js";
import type { MarketSeries } from "../marketDataTypes.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";

interface WarmStream {
  controller: KlineStreamController;
  timer: ReturnType<typeof setTimeout>;
  leases: Set<symbol>;
  retained: boolean;
  priority: number;
}

/** A small speculative tier. Closing these leases never closes another chart's
 * shared subscription. Expiry is mandatory even when a caller forgets release. */
export class MarketWarmStreams {
  private readonly entries = new Map<string, WarmStream>();
  private evicted = 0;
  constructor(private readonly subscribe: KlineStreamFactory, private readonly maxSeries = 4,
    private readonly ttlMs = 30_000) {}

  acquire(series: MarketSeries, reason: WarmReason): { retain(): void; release(): void } {
    const key = String(buildSeriesWindowKey(series));
    const priority = { hover: 0, frequent: 1, watchlist: 2 }[reason];
    let entry = this.entries.get(key);
    if (!entry) {
      while (this.entries.size >= Math.max(1, this.maxSeries)) {
        const victim = [...this.entries].sort((a, b) => b[1].priority - a[1].priority)[0]!;
        if (victim[1].priority < priority) return { retain() {}, release() {} };
        this.drop(victim[0]); this.evicted += 1;
      }
      const controller = this.subscribe(series, { intervals: [series.interval],
        onClose: () => this.drop(key), onError: () => this.drop(key) });
      entry = { controller, timer: setTimeout(() => this.drop(key), this.ttlMs), leases: new Set(), retained: false, priority };
      this.entries.set(key, entry);
    }
    const target = entry, id = Symbol(key);
    target.leases.add(id); target.priority = Math.min(target.priority, priority);
    this.entries.delete(key); this.entries.set(key, target);
    return {
      retain: () => { if (this.entries.get(key) === target) target.retained = true; },
      release: () => {
        target.leases.delete(id);
        if (!target.retained && !target.leases.size && this.entries.get(key) === target) this.drop(key);
      },
    };
  }

  promote(series: MarketSeries): void {
    const entry = this.entries.get(String(buildSeriesWindowKey(series)));
    if (entry) entry.retained = true;
  }

  diagnostics() { return { series: this.entries.size, maxSeries: this.maxSeries, ttlMs: this.ttlMs, evicted: this.evicted }; }
  dispose(): void { for (const key of [...this.entries.keys()]) this.drop(key); }
  private drop(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    this.entries.delete(key); clearTimeout(entry.timer); entry.controller.close();
  }
}
