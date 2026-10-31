import type { MarketSeries } from "../marketDataTypes.js";
import { buildSeriesWindowKey } from "../window/seriesWindowKey.js";

/** Bounded verification executor. Eligibility lives in the cache; this queue
 * only coalesces and executes IO. A failed attempt never grants health. */
export class MarketHealthRecovery {
  private readonly pending = new Map<string, MarketSeries>();
  private readonly active = new Map<string, AbortController>();
  private readonly recent = new Map<string, number>();
  private readonly spent: number[] = [];
  private disposed = false;
  constructor(private readonly needed: (series: MarketSeries) => number,
    private readonly read: (series: MarketSeries, limit: number, signal: AbortSignal) => Promise<unknown>) {}

  request(series: MarketSeries): void {
    if (this.disposed || !this.needed(series)) return;
    const key = String(buildSeriesWindowKey(series)), now = Date.now();
    if (this.active.has(key) || this.pending.has(key) || (this.recent.get(key) ?? 0) > now || this.pending.size >= 8) return;
    this.pending.set(key, { ...series }); this.pump();
  }

  diagnostics() { return { active: this.active.size, pending: this.pending.size, attemptsInMinute: this.spent.length }; }
  dispose(): void {
    this.disposed = true; this.pending.clear(); this.recent.clear();
    for (const controller of this.active.values()) controller.abort();
  }

  private pump(): void {
    if (this.disposed) return;
    const now = Date.now();
    while (this.spent.length && this.spent[0]! <= now - 60_000) this.spent.shift();
    for (const [key, until] of this.recent) if (until <= now) this.recent.delete(key);
    // At most 12 bounded reads/minute; later real events retry eligibility.
    if (this.spent.length >= 12) { this.pending.clear(); return; }
    for (const [key, series] of this.pending) {
      if (this.active.size >= 2 || this.spent.length >= 12) break;
      this.pending.delete(key);
      const limit = this.needed(series);
      if (!limit) continue;
      const controller = new AbortController();
      this.active.set(key, controller); this.spent.push(now); this.recent.set(key, now + 5_000);
      void this.read(series, limit, controller.signal).catch(() => undefined).finally(() => {
        this.active.delete(key); this.pump();
      });
    }
  }
}
