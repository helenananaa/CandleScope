import type { MarketHistoryRange } from "../advanced-market-data/marketHistoryCoverage.js";
import { fetchLiquidationHistory } from "./liquidationApi.js";
import type { LiquidationHistoryPayload, LiquidationIdentity, LiquidationPositionSide } from "./liquidationTypes.js";

/** One claimed range owns its advancing cursor, independently of cache
 * retention. Every page remains cancellable and only one request is in flight. */
export async function loadLiquidationHistoryPages({
  identity, side, range, signal, isCurrent, onPage, fetchPage = fetchLiquidationHistory,
}: {
  identity: LiquidationIdentity;
  side: LiquidationPositionSide;
  range: MarketHistoryRange;
  signal: AbortSignal;
  isCurrent(): boolean;
  onPage(payload: LiquidationHistoryPayload, covered: MarketHistoryRange): void;
  fetchPage?: typeof fetchLiquidationHistory;
}): Promise<void> {
  let cursor = range.startMs;
  while (cursor <= range.endMs && !signal.aborted && isCurrent()) {
    const payload = await fetchPage(identity, {
      positionSide: side, startMs: cursor, endMs: range.endMs, limit: 5000, signal,
    });
    if (signal.aborted || !isCurrent()) return;
    if (payload.key.exchange !== identity.exchange.toLowerCase()
      || payload.key.market_type !== identity.marketType.toLowerCase()
      || payload.key.symbol !== identity.symbol.toUpperCase()
      || payload.key.params.period !== "1m"
      || payload.key.params.position_side !== side) {
      throw new Error(`Liquidation ${side} history identity did not match the request`);
    }
    const tail = payload.data.at(-1);
    if (payload.hasMore && (!tail || tail.bucketStartMs < cursor)) {
      throw new Error(`Liquidation ${side} history did not advance its cursor`);
    }
    const endMs = payload.hasMore && tail
      ? Math.min(range.endMs, tail.bucketStartMs + 60_000 - 1)
      : range.endMs;
    onPage(payload, { startMs: cursor, endMs });
    if (!payload.hasMore) return;
    cursor = endMs + 1;
  }
}
