import type { AdvancedMarketConnectionStatus } from "../advanced-market-data/advancedMarketDataTypes.js";
import { mergeHistoryCoverage, type MarketHistoryRange } from "../advanced-market-data/marketHistoryCoverage.js";
import { subtractLiquidationHistoryRanges } from "./liquidationHistoryRequests.js";
import type {
  LiquidationEvent,
  LiquidationIdentity,
  LiquidationQualityMetadata,
  LiquidationRollup,
  LiquidationSnapshot,
  LiquidationPositionSide,
} from "./liquidationTypes.js";

const MAX_ROLLUPS_PER_IDENTITY = 100_000;
const MAX_LIVE_EVENTS_PER_IDENTITY = 10_000;

export const EMPTY_LIQUIDATION_SNAPSHOT: LiquidationSnapshot = Object.freeze({
  rollups: Object.freeze([]),
  liveEvents: Object.freeze([]),
  connectionStatus: "disabled",
  quality: null,
  revision: 0,
});

interface LiquidationEntry {
  rollups: Map<string, LiquidationRollup>;
  liveEvents: Map<string, LiquidationEvent>;
  sortedRollups: readonly LiquidationRollup[];
  sortedLiveEvents: readonly LiquidationEvent[];
  listeners: Set<() => void>;
  connectionStatus: AdvancedMarketConnectionStatus;
  quality: LiquidationQualityMetadata | null;
  revision: number;
  snapshot: LiquidationSnapshot;
  coverage: Map<LiquidationPositionSide, MarketHistoryRange[]>;
  leases: number;
}

function identityKey(identity: LiquidationIdentity): string {
  return [
    identity.exchange.trim().toLowerCase(),
    identity.marketType.trim().toLowerCase(),
    identity.symbol.trim().toUpperCase(),
  ].join(":");
}

function rollupKey(rollup: Pick<LiquidationRollup, "bucketStartMs" | "positionSide">): string {
  return `${rollup.bucketStartMs}:${rollup.positionSide}`;
}

function eventMatchesIdentity(event: LiquidationEvent, expectedIdentityKey: string): boolean {
  return identityKey({
    exchange: event.exchange,
    marketType: event.marketType,
    symbol: event.symbol,
  }) === expectedIdentityKey;
}

function rollupMatchesIdentity(rollup: LiquidationRollup, expectedIdentityKey: string): boolean {
  return identityKey({
    exchange: rollup.exchange,
    marketType: rollup.marketType,
    symbol: rollup.symbol,
  }) === expectedIdentityKey;
}

function shouldReplaceRollup(
  current: LiquidationRollup | undefined,
  incoming: LiquidationRollup,
): boolean {
  if (!current) return true;
  if (current.isFinal !== incoming.isFinal) return incoming.isFinal;
  if (incoming.updatedAtMs !== current.updatedAtMs) {
    return incoming.updatedAtMs > current.updatedAtMs;
  }
  return incoming.revision > current.revision;
}

function rollupCoversEvent(rollup: LiquidationRollup | undefined, event: LiquidationEvent): boolean {
  if (!rollup) return false;
  if (rollup.updatedAtMs > event.receivedAtMs) return true;
  return rollup.updatedAtMs === event.receivedAtMs
    && rollup.lastEventTimeMs >= event.tradeTimeMs;
}

function mergeSortedChanges<T>(
  current: readonly T[],
  changes: readonly T[],
  keyOf: (value: T) => string,
  compare: (left: T, right: T) => number,
): readonly T[] {
  if (changes.length === 0) return current;
  const changedKeys = new Set(changes.map(keyOf));
  const retained = current.filter((value) => !changedKeys.has(keyOf(value)));
  const sortedChanges = [...changes].sort(compare);
  const merged: T[] = [];
  let currentIndex = 0;
  let changeIndex = 0;
  while (currentIndex < retained.length || changeIndex < sortedChanges.length) {
    const currentValue = retained[currentIndex];
    const changedValue = sortedChanges[changeIndex];
    if (changedValue === undefined || (
      currentValue !== undefined && compare(currentValue, changedValue) <= 0
    )) {
      if (currentValue !== undefined) merged.push(currentValue);
      currentIndex += 1;
    } else {
      merged.push(changedValue);
      changeIndex += 1;
    }
  }
  return Object.freeze(merged);
}

function trimOldestEvents(
  values: Map<string, LiquidationEvent>,
  sortedValues: readonly LiquidationEvent[],
  limit: number,
): readonly LiquidationEvent[] {
  if (values.size <= limit) return sortedValues;
  const excess = values.size - limit;
  // Stable sort preserves Map insertion order for equal receipt timestamps,
  // exactly as the previous repeated oldest-event scan did.
  const oldest = [...values.values()].sort((left, right) => left.receivedAtMs - right.receivedAtMs);
  const removed = new Set(oldest.slice(0, excess).map((event) => event.fingerprint));
  for (const fingerprint of removed) {
    values.delete(fingerprint);
  }
  return removed.size === 0
    ? sortedValues
    : Object.freeze(sortedValues.filter((event) => !removed.has(event.fingerprint)));
}

const compareRollups = (left: LiquidationRollup, right: LiquidationRollup): number => (
  left.bucketStartMs - right.bucketStartMs
  || left.positionSide.localeCompare(right.positionSide)
);

const compareEvents = (left: LiquidationEvent, right: LiquidationEvent): number => (
  left.tradeTimeMs - right.tradeTimeMs
  || left.receivedAtMs - right.receivedAtMs
  || left.fingerprint.localeCompare(right.fingerprint)
);

function createEntry(): LiquidationEntry {
  return {
    rollups: new Map(),
    liveEvents: new Map(),
    sortedRollups: Object.freeze([]),
    sortedLiveEvents: Object.freeze([]),
    listeners: new Set(),
    connectionStatus: "disabled",
    quality: null,
    revision: 0,
    snapshot: EMPTY_LIQUIDATION_SNAPSHOT,
    coverage: new Map(),
    leases: 0,
  };
}

export class LiquidationStore {
  private readonly entries = new Map<string, LiquidationEntry>();

  constructor(private readonly limits: {
    maxEntries?: number;
    maxRollupsPerIdentity?: number;
    maxLiveEventsPerIdentity?: number;
    maxTotalRecords?: number;
  } = {}) {}

  retain(identity: LiquidationIdentity): () => void {
    const key = identityKey(identity);
    const entry = this.entry(key);
    entry.leases += 1;
    this.enforceBudget();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      entry.leases -= 1;
      if (entry.leases === 0 && entry.listeners.size === 0) this.entries.delete(key);
      this.enforceBudget();
    };
  }

  subscribe(identity: LiquidationIdentity | string, listener: () => void): () => void {
    const key = typeof identity === "string" ? identity : identityKey(identity);
    const entry = this.entry(key);
    entry.listeners.add(listener);
    this.enforceBudget();
    return () => {
      entry.listeners.delete(listener);
      if (entry.leases === 0 && entry.listeners.size === 0) this.entries.delete(key);
      this.enforceBudget();
    };
  }

  historyCoverage(identity: LiquidationIdentity, side: LiquidationPositionSide): readonly MarketHistoryRange[] {
    return this.entries.get(identityKey(identity))?.coverage.get(side) ?? [];
  }

  invalidateHistoryCoverage(identity: LiquidationIdentity, range?: MarketHistoryRange): void {
    const entry = this.entries.get(identityKey(identity));
    if (!entry) return;
    if (!range) entry.coverage.clear();
    else for (const [side, coverage] of entry.coverage) {
      entry.coverage.set(side, subtractLiquidationHistoryRanges(coverage, [range]));
    }
  }

  getSnapshot(identity: LiquidationIdentity | string): LiquidationSnapshot {
    const key = typeof identity === "string" ? identity : identityKey(identity);
    return this.entries.get(key)?.snapshot ?? EMPTY_LIQUIDATION_SNAPSHOT;
  }

  mergeHistory(
    identity: LiquidationIdentity,
    rollups: readonly LiquidationRollup[],
    quality: LiquidationQualityMetadata,
    covered?: { side: LiquidationPositionSide; range: MarketHistoryRange },
  ): void {
    const key = identityKey(identity);
    const entry = this.entry(key);
    let changed = entry.quality !== quality;
    const changedRollups = new Map<string, LiquidationRollup>();
    entry.quality = quality;
    if (covered) entry.coverage.set(covered.side, mergeHistoryCoverage(
      entry.coverage.get(covered.side) ?? [], covered.range,
    ));
    for (const rollup of rollups) {
      if (!rollupMatchesIdentity(rollup, key)) continue;
      const naturalKey = rollupKey(rollup);
      const current = entry.rollups.get(naturalKey);
      // Recently requested historical pages must survive a revisit even when
      // newer timestamps previously filled the cache.
      if (current) {
        entry.rollups.delete(naturalKey);
        entry.rollups.set(naturalKey, current);
      }
      if (!shouldReplaceRollup(current, rollup)) continue;
      entry.rollups.set(naturalKey, rollup);
      changedRollups.set(naturalKey, rollup);
      changed = true;
    }
    if (changedRollups.size > 0) {
      entry.sortedRollups = mergeSortedChanges(
        entry.sortedRollups,
        [...changedRollups.values()],
        rollupKey,
        compareRollups,
      );
    }
    const retainedLiveEvents: LiquidationEvent[] = [];
    for (const event of entry.sortedLiveEvents) {
      const base = entry.rollups.get(rollupKey({
        bucketStartMs: Math.floor(event.tradeTimeMs / 60_000) * 60_000,
        positionSide: event.positionSide,
      }));
      if (rollupCoversEvent(base, event)) {
        entry.liveEvents.delete(event.fingerprint);
        changed = true;
      } else {
        retainedLiveEvents.push(event);
      }
    }
    if (retainedLiveEvents.length !== entry.sortedLiveEvents.length) {
      entry.sortedLiveEvents = Object.freeze(retainedLiveEvents);
    }
    this.trimRollups(entry, this.limits.maxRollupsPerIdentity ?? MAX_ROLLUPS_PER_IDENTITY);
    if (changed) this.publish(entry);
    this.enforceBudget();
  }

  applyEvents(
    identity: LiquidationIdentity,
    events: readonly LiquidationEvent[],
    quality: LiquidationQualityMetadata,
  ): void {
    const key = identityKey(identity);
    const entry = this.entry(key);
    let changed = entry.quality !== quality;
    const changedEvents: LiquidationEvent[] = [];
    entry.quality = quality;
    for (const event of events) {
      if (!eventMatchesIdentity(event, key) || entry.liveEvents.has(event.fingerprint)) continue;
      const base = entry.rollups.get(rollupKey({
        bucketStartMs: Math.floor(event.tradeTimeMs / 60_000) * 60_000,
        positionSide: event.positionSide,
      }));
      if (rollupCoversEvent(base, event)) continue;
      entry.liveEvents.set(event.fingerprint, event);
      changedEvents.push(event);
      changed = true;
    }
    if (changedEvents.length > 0) {
      entry.sortedLiveEvents = mergeSortedChanges(
        entry.sortedLiveEvents,
        changedEvents,
        (event) => event.fingerprint,
        compareEvents,
      );
    }
    entry.sortedLiveEvents = trimOldestEvents(
      entry.liveEvents,
      entry.sortedLiveEvents,
      this.limits.maxLiveEventsPerIdentity ?? MAX_LIVE_EVENTS_PER_IDENTITY,
    );
    if (changed) this.publish(entry);
    this.enforceBudget();
  }

  setConnectionStatus(
    identity: LiquidationIdentity,
    status: AdvancedMarketConnectionStatus,
    quality?: LiquidationQualityMetadata | null,
  ): void {
    const key = identityKey(identity);
    if ((status === "disabled" || status === "disconnected") && !this.entries.has(key)) return;
    const entry = this.entry(key);
    const nextQuality = quality === undefined ? entry.quality : quality;
    if (entry.connectionStatus === status && entry.quality === nextQuality) return;
    entry.connectionStatus = status;
    entry.quality = nextQuality;
    this.publish(entry);
    this.enforceBudget();
  }

  clearUnconfirmed(identity: LiquidationIdentity): void {
    const entry = this.entry(identityKey(identity));
    let changed = entry.liveEvents.size > 0;
    entry.liveEvents.clear();
    entry.sortedLiveEvents = Object.freeze([]);
    entry.coverage.clear();
    for (const [key, row] of entry.rollups) {
      if (row.isFinal) continue;
      entry.rollups.delete(key);
      changed = true;
    }
    if (changed) {
      entry.sortedRollups = Object.freeze(
        entry.sortedRollups.filter((row) => row.isFinal),
      );
    }
    if (changed) this.publish(entry);
  }

  clearForTests(): void {
    this.entries.clear();
  }

  private entry(key: string): LiquidationEntry {
    let entry = this.entries.get(key);
    if (!entry) {
      entry = createEntry();
      this.entries.set(key, entry);
    } else {
      this.entries.delete(key);
      this.entries.set(key, entry);
    }
    return entry;
  }

  private trimRollups(entry: LiquidationEntry, limit: number): void {
    if (entry.rollups.size <= limit) return;
    const removed = new Set<string>();
    const missing = new Map<LiquidationPositionSide, MarketHistoryRange[]>();
    for (const [key, row] of entry.rollups) {
      if (entry.rollups.size <= limit) break;
      entry.rollups.delete(key);
      removed.add(key);
      const ranges = missing.get(row.positionSide) ?? [];
      ranges.push({ startMs: row.bucketStartMs, endMs: row.bucketEndMs - 1 });
      missing.set(row.positionSide, ranges);
    }
    entry.sortedRollups = Object.freeze(entry.sortedRollups.filter((row) => !removed.has(rollupKey(row))));
    for (const [side, gaps] of missing) {
      entry.coverage.set(side, subtractLiquidationHistoryRanges(entry.coverage.get(side) ?? [], gaps));
    }
  }

  private enforceBudget(): void {
    const maxEntries = this.limits.maxEntries ?? 16;
    const maxRecords = this.limits.maxTotalRecords ?? 200_000;
    let total = [...this.entries.values()].reduce((sum, entry) => (
      sum + entry.rollups.size + entry.liveEvents.size
    ), 0);
    for (const [key, entry] of this.entries) {
      if (this.entries.size <= maxEntries && total <= maxRecords) break;
      if (entry.leases > 0 || entry.listeners.size > 0) continue;
      total -= entry.rollups.size + entry.liveEvents.size;
      this.entries.delete(key);
    }
    // Active identities retain their entry and subscribers. Their oldest data
    // can still be trimmed to honor the process-wide record budget.
    for (const entry of this.entries.values()) {
      if (total <= maxRecords) break;
      const before = entry.rollups.size + entry.liveEvents.size;
      this.trimRollups(entry, Math.max(0, entry.rollups.size - (total - maxRecords)));
      const excess = total - maxRecords - (before - entry.rollups.size - entry.liveEvents.size);
      if (excess > 0) entry.sortedLiveEvents = trimOldestEvents(
        entry.liveEvents, entry.sortedLiveEvents, Math.max(0, entry.liveEvents.size - excess),
      );
      const after = entry.rollups.size + entry.liveEvents.size;
      if (before !== after) this.publish(entry);
      total -= before - after;
    }
  }

  private publish(entry: LiquidationEntry): void {
    entry.revision += 1;
    entry.snapshot = Object.freeze({
      rollups: Object.freeze(
        entry.sortedRollups,
      ),
      liveEvents: Object.freeze(
        entry.sortedLiveEvents,
      ),
      connectionStatus: entry.connectionStatus,
      quality: entry.quality,
      revision: entry.revision,
    });
    for (const listener of entry.listeners) listener();
  }
}

export const liquidationStore = new LiquidationStore();
