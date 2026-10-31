import type { SharedMarketCache } from "../market-data/manager/sharedMarketCache.js";
import type { CacheTrimOwnerResult, GcVictim } from "./cacheGcTypes.js";
import { klineDependencyKey, registerKlineAvailabilityProvider } from "./cacheRegistry.js";

const owners = new Map<string, SharedMarketCache>();
let sequence = 0;
const OWNER = "shared-market-cache";
const ROW_BYTES = 200;

/** Registration belongs to the mounted workspace, never a module-global data pool. */
export function registerSharedMarketCache(cache: SharedMarketCache): () => void {
  const id = String(++sequence);
  owners.set(id, cache);
  const release = registerKlineAvailabilityProvider(key => cache.diagnosticEntries().some(entry => entry.bars > 0 && klineDependencyKey(entry.series) === key));
  return () => { owners.delete(id); release(); };
}

export function snapshotSharedMarketCacheDiagnostics() {
  const entries = [...owners].flatMap(([id, cache]) => cache.diagnosticEntries().map(entry => ({
    owner: OWNER, key: `${id}\u0000${entry.key}`, generation: entry.generation,
    metaRevision: entry.metaRevision, bars: entry.bars, estimatedBytes: entry.bars * ROW_BYTES,
    tier: entry.protected ? "active" : "warm", lastAccessMs: entry.lastAccessMs, lastUpdatedMs: entry.lastUpdatedMs,
    ...entry.series,
  })));
  const totalBars = entries.reduce((total, entry) => total + entry.bars, 0);
  return { owner: OWNER, entries, seriesCount: entries.length, totalBars, estimatedBytes: totalBars * ROW_BYTES };
}

export function trimSharedMarketCacheEntries(victims: readonly GcVictim[]): CacheTrimOwnerResult {
  const skipped: Array<{ key: string; reason: string }> = [];
  let removedCount = 0, removedBars = 0;
  for (const victim of new Map(victims.map(item => [item.key, item])).values()) {
    const split = victim.key.indexOf("\u0000");
    const cache = owners.get(victim.key.slice(0, split));
    const bars = Number(victim.resourceTotals?.bars);
    const bytes = bars * ROW_BYTES;
    const matches = Number.isInteger(bars) && bars >= 0 && victim.action === "delete-entry"
      && victim.bars === bars && victim.estimatedBytes === bytes
      && victim.resourceTotals?.estimatedBytes === bytes
      && (!victim.relief || (victim.relief.bars === bars && victim.relief.estimatedBytes === bytes));
    if (!matches || !cache?.evictIfUnchanged(victim.key.slice(split + 1), Number(victim.generation), Number(victim.expectedMetaRevision), bars)) {
      skipped.push({ key: victim.key, reason: "shared-cache-plan-stale-or-protected" });
      continue;
    }
    removedCount += 1; removedBars += bars;
  }
  return { owner: OWNER, removedCount, removedBars, removedEstimatedBytes: removedBars * ROW_BYTES, skipped };
}
