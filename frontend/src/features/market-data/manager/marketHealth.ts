import { canonicalizeIntervalValue } from "../../../utils/intervals.js";
import type { MarketSeries } from "../marketDataTypes.js";
import { resolveKlineSeriesIdentity } from "../klineSeriesIdentity.js";

export interface MarketStreamVersion {
  protocol: 1;
  epoch: string;
  generation: number;
  sequence: number;
  barrier: number;
  observed_at_ms: number;
  stable?: boolean;
}

/** A wire version is meaningful only in its exact server-owned series scope. */
export function parseMarketVersion(value: unknown, series: MarketSeries): MarketStreamVersion | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (v.protocol !== 1 || typeof v.epoch !== "string" || !v.epoch || v.epoch.length > 128
    || ![v.generation, v.sequence, v.barrier, v.observed_at_ms].every(n => Number.isSafeInteger(n) && Number(n) >= 0)
    || Number(v.barrier) > Number(v.sequence)) return null;
  const scope = v.series as Record<string, unknown> | undefined;
  const semantic = resolveKlineSeriesIdentity(series.exchange, series);
  const expected = { exchange: series.exchange.trim().toLowerCase(), market_type: series.marketType.trim().toLowerCase(),
    symbol: series.symbol.trim().toUpperCase(), interval: canonicalizeIntervalValue(series.interval),
    provider_id: semantic.providerId, venue: semantic.venue, asset_class: semantic.assetClass,
    series_variant: semantic.seriesVariant, price_adjustment: semantic.priceAdjustment,
    session_variant: semantic.sessionVariant, volume_semantics: semantic.volumeSemantics };
  if (!scope || Object.entries(expected).some(([key, val]) => scope[key] !== val)) return null;
  return Object.freeze({ protocol: 1, epoch: v.epoch, generation: Number(v.generation), sequence: Number(v.sequence),
    barrier: Number(v.barrier), observed_at_ms: Number(v.observed_at_ms), ...(v.stable === undefined ? {} : { stable: v.stable === true }) });
}

export function sameStream(a: MarketStreamVersion | null, b: MarketStreamVersion | null): boolean {
  return Boolean(a && b && a.epoch === b.epoch && a.generation === b.generation);
}

export interface MarketHealth {
  historyCovered: boolean;
  subscribed: boolean;
  continuous: boolean;
  fresh: boolean;
  healthy: boolean;
  reason: "healthy" | "missing-history" | "unsubscribed" | "resync" | "stale-tail";
}
export interface HealthReadFence { connection: number; invalidation: number; version: MarketStreamVersion | null }

/** No data or network here: health evidence belongs to the cache entry. */
export class MarketHealthState {
  version: MarketStreamVersion | null = null;
  private connection = 0;
  private invalidation = 0;
  private subscribed = false;
  private continuous = false;
  private lastEvent: MarketStreamVersion | null = null;
  private receivedAt = 0;
  private baseline: MarketStreamVersion | null = null;
  private freshObservedAt = 0;
  private readonly retired = new Set<string>();
  private requiresReconnect = false;

  constructor(private readonly now: () => number = Date.now, private readonly freshMs = 15_000) {}

  fence(): HealthReadFence { return { connection: this.connection, invalidation: this.invalidation, version: this.version }; }
  connect(): void { if (!this.subscribed) { this.subscribed = true; this.connection += 1; this.continuous = false; } }
  disconnect(revokeReads = true): void {
    this.subscribed = false; this.connection += 1;
    if (revokeReads) this.invalidation += 1;
    this.continuous = false;
    this.lastEvent = null; this.receivedAt = 0; this.baseline = null;
    this.retired.clear(); this.requiresReconnect = false;
  }
  invalidate(): void { this.continuous = false; this.baseline = null; }

  snapshot(version: MarketStreamVersion | null, fence: HealthReadFence): boolean {
    if (fence.invalidation !== this.invalidation) return false;
    if (!version || version.stable !== true) {
      this.invalidate();
      // A freshly read legacy server after reconnect may render through the
      // old request fence. Do not mix unversioned ticks into a bound v1 stream.
      if (this.lastEvent === null) this.version = null;
      return true;
    }
    if (this.requiresReconnect || this.retired.has(this.incarnation(version))) return false;
    if (this.version?.epoch === version.epoch && version.generation < this.version.generation) return false;
    // A response from before a stream incarnation change cannot resurrect it.
    if (this.version && !sameStream(this.version, version)
      && (!sameStream(fence.version, this.version) || fence.connection !== this.connection)) return false;
    if (this.version && sameStream(this.version, version) && version.sequence < this.version.sequence
      && version.barrier !== this.version.barrier) return false;
    const linked = sameStream(this.lastEvent, version)
      && (this.lastEvent!.sequence <= version.sequence || this.lastEvent!.barrier === version.barrier);
    this.baseline = version.stable === true && this.subscribed && fence.connection === this.connection ? version : null;
    this.continuous = this.baseline !== null && linked;
    if ((!sameStream(this.version, version) || version.sequence >= this.version!.sequence) && !this.adopt(version)) return false;
    return true;
  }

  event(version: MarketStreamVersion | null, critical: boolean, fresh = true): { accept: boolean; reset: boolean; gap: boolean } {
    if (!version) { this.invalidate(); return { accept: this.version === null, reset: false, gap: false }; }
    if (this.requiresReconnect || this.retired.has(this.incarnation(version))) return { accept: false, reset: false, gap: false };
    const previous = this.version;
    const reset = previous !== null && !sameStream(previous, version);
    if (previous && previous.epoch === version.epoch && version.generation < previous.generation) return { accept: false, reset: false, gap: false };
    if (reset && sameStream(this.lastEvent, version) && !sameStream(this.lastEvent, previous)) return { accept: false, reset: false, gap: false };
    if (reset) this.invalidate();
    if (!reset && previous && version.sequence < previous.sequence) return { accept: false, reset: false, gap: false };
    if (!reset && previous && version.sequence === previous.sequence) {
      // A matching event can confirm a snapshot/stream cutover without
      // applying the same version a second time.
      if (version.barrier !== previous.barrier) { this.invalidate(); return { accept: false, reset: false, gap: true }; }
      const advances = !sameStream(this.lastEvent, version) || this.lastEvent!.sequence < version.sequence;
      this.lastEvent = version;
      if (fresh && advances) { this.receivedAt = this.now(); this.freshObservedAt = version.observed_at_ms; }
      if (this.baseline && sameStream(this.baseline, version) && this.baseline.barrier === version.barrier) this.continuous = true;
      return { accept: true, reset: false, gap: false };
    }
    const gap = Boolean(previous && !reset && version.barrier !== previous.barrier + (critical ? 1 : 0));
    if (gap) this.invalidate();
    else if (this.baseline && sameStream(this.baseline, version)) this.continuous = true;
    if (!this.adopt(version)) return { accept: false, reset: false, gap: false };
    this.lastEvent = version;
    if (fresh) { this.receivedAt = this.now(); this.freshObservedAt = version.observed_at_ms; }
    return { accept: true, reset, gap };
  }

  private incarnation(version: MarketStreamVersion): string { return `${version.epoch}:${version.generation}`; }
  private adopt(version: MarketStreamVersion): boolean {
    if (this.version && !sameStream(this.version, version)) {
      // Do not evict a rejection fence and accidentally accept an ancient
      // queued incarnation. A fresh physical connection resets this budget.
      if (this.retired.size >= 64) { this.requiresReconnect = true; this.invalidate(); return false; }
      this.retired.add(this.incarnation(this.version));
    }
    this.version = version;
    return true;
  }

  status(historyCovered: boolean): MarketHealth {
    const now = this.now();
    const fresh = this.lastEvent !== null && now - this.receivedAt <= this.freshMs
      && now - this.freshObservedAt <= this.freshMs && this.freshObservedAt <= now + 5_000;
    const reason = !historyCovered ? "missing-history" : !this.subscribed ? "unsubscribed"
      : !this.continuous ? "resync" : !fresh ? "stale-tail" : "healthy";
    return { historyCovered, subscribed: this.subscribed, continuous: this.continuous, fresh,
      healthy: reason === "healthy", reason };
  }
}
