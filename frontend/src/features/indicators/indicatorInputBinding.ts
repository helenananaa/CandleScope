import type { KlineBar, MarketSeries } from "../market-data/marketDataTypes.js";
import type { MarketInputVersion, SharedMarketCache } from "../market-data/manager/sharedMarketCache.js";

export interface IndicatorCacheInputSource {
  readonly scope: string;
  /** Hosted recursive calculations depend on the observed prefix, not only outputs. */
  capture(series: MarketSeries, through: number, from?: number): MarketInputVersion;
  /** Provided-bar calculations must describe exactly their actual bounded input. */
  captureProvided(series: MarketSeries, rows: readonly KlineBar[]): MarketInputVersion | null;
}

const sources = new WeakMap<SharedMarketCache, IndicatorCacheInputSource>();
let nextScope = 0;
const INPUT_FIELDS = ["time", "open", "high", "low", "close", "volume"] as const;

/** Window delta recovery already covers its retained rows. A recursive hosted
 * indicator can also depend on earlier facts learned by a different chart. */
export function bindSharedIndicatorPrefix(
  cache: SharedMarketCache,
  series: MarketSeries,
  firstWindowTime: () => number | undefined,
  onDirty: (range: { start: number; end: number }) => void,
): () => void {
  return cache.subscribe(series, change => {
    const first = firstWindowTime();
    if (first === undefined || (change.source !== "http" && change.eventType !== "bar.amended")) return;
    const earlier = change.rows.filter(row => Number(row.time) < first);
    if (!earlier.length) return;
    onDirty({ start: Math.min(...earlier.map(row => Number(row.time))), end: Math.max(...earlier.map(row => Number(row.time))) });
  });
}

export function createIndicatorCacheInputSource(cache: SharedMarketCache): IndicatorCacheInputSource {
  const existing = sources.get(cache);
  if (existing) return existing;
  const source: IndicatorCacheInputSource = Object.freeze({
    scope: `market-input-${++nextScope}`,
    capture: (series: MarketSeries, through: number, from?: number) => cache.captureVersion(series,
      { to: through, ...(from === undefined ? {} : { from }) }),
    captureProvided: (series: MarketSeries, rows: readonly KlineBar[]) => {
      if (!rows.length) return null;
      const range = { from: Number(rows[0]!.time), to: Number(rows.at(-1)!.time) };
      const shared = cache.read(series, range);
      if (shared.rows.length !== rows.length || rows.some((row, index) => {
        const held = shared.rows[index]!;
        return INPUT_FIELDS.some(field => Number(row[field] ?? 0) !== Number(held[field] ?? 0))
          || row.is_closed !== held.is_closed;
      })) return null;
      return cache.captureVersion(series, range);
    },
  });
  sources.set(cache, source);
  return source;
}
