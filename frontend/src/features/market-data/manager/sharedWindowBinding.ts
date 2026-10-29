import { klineRowsEqual } from "../chartDataRuntime.js";
import type { KlineBar, MarketSeries } from "../marketDataTypes.js";
import { assessKlineQuality, type KlineQualityEvidence } from "../quality/klineQualityPolicy.js";
import type { SharedMarketCache } from "./sharedMarketCache.js";

export interface SharedWindowConsumer {
  read(): readonly KlineBar[];
  /** Must use the window's current selection transaction, never a raw Store. */
  commit(rows: KlineBar[], quality: KlineQualityEvidence): void;
}

/** Corrections learned by another consumer may update a retained window, but
 * cannot advance its right edge or evict its left edge. Navigation still owns
 * range expansion. WS delivery keeps the existing per-consumer recovery/quote
 * callback, after shared admission, so amendment readback sees the old row. */
export function bindSharedWindow(cache: SharedMarketCache, series: MarketSeries, consumer: SharedWindowConsumer): () => void {
  return cache.subscribe(series, change => {
    if (change.source !== "http" || !change.rows.length) return;
    const current = consumer.read();
    const first = current[0]?.time, last = current.at(-1)?.time;
    if (first === undefined || last === undefined) return;
    const held = new Map(current.map(row => [row.time, row]));
    const rows = change.rows.filter(row => row.time >= first && row.time <= last
      && (!held.has(row.time) || !klineRowsEqual([held.get(row.time)!], [row])))
      .sort((left, right) => left.time - right.time);
    if (!rows.length) return;
    const snapshot = cache.read(series, { from: rows[0]!.time, to: rows.at(-1)!.time });
    const quality = assessKlineQuality({ data: rows, complete: snapshot.complete,
      all_rows_final: rows.every(row => row.is_closed === true), retryable: !snapshot.complete,
      history_state: snapshot.complete ? "ready" : "pending", verified_contiguous: snapshot.complete,
      has_tail_gap: false, truncated: false, missing_ranges: [] }, "range");
    consumer.commit(rows, quality);
  });
}
