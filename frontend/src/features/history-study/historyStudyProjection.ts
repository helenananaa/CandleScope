import { createIntervalTimeline } from "../../utils/intervalTimeline.js";
import { aggregateReplayBaseBars } from "../replay/replayViewerProjection.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import { toEpochSeconds } from "../market-data/marketDataTypes.js";
import type { StudyBar } from "./historyStudyTypes.js";

/** Reuse the existing calendar-aware replay aggregation. Input contains only
 * revealed, closed source candles. A missing start or internal component
 * makes the whole display bucket unavailable, rather than a fabricated open
 * or a misleading final candle. No prices are read from a later bucket. */
export function projectStudyBars(rows: readonly StudyBar[], sourceInterval: string, displayInterval: string): {
  rows: readonly KlineBar[]; missingBuckets: number[];
} {
  if (sourceInterval === displayInterval) return { rows: rows.map(row => ({ ...row, time: toEpochSeconds(row.time)! })), missingBuckets: [] };
  const source = createIntervalTimeline(sourceInterval)!, display = createIntervalTimeline(displayInterval)!;
  const invalid = new Set<number>();
  let bucket: number | null = null, previous: number | null = null;
  for (const row of rows) {
    const start = display.floor(row.time)!;
    if (start !== bucket) {
      bucket = start;
      if (row.time !== start) invalid.add(start);
    } else if (previous !== null && !source.isSuccessor(previous, row.time)) invalid.add(start);
    previous = row.time;
  }
  const normalized = rows.map(row => ({ ...row, time: toEpochSeconds(row.time)!, replayClosed: true,
    quoteVolume: row.quote_volume, takerBuyBase: row.taker_buy_base, takerBuyQuote: row.taker_buy_quote }));
  const aggregated = aggregateReplayBaseBars(normalized, sourceInterval, displayInterval);
  return { rows: aggregated.filter(row => !invalid.has(row.time)), missingBuckets: [...invalid] };
}
