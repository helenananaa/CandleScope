import type { MarketHistoryRange } from "../advanced-market-data/marketHistoryCoverage.js";
import { ApiPayloadError } from "../../services/apiPayloadParsers.js";
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
  onPage(payload: LiquidationHistoryPayload, scanned: MarketHistoryRange): void;
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
      throw new ApiPayloadError("liquidations.history.key", `${side} history identity did not match the request`);
    }
    if (!payload.hasMore) {
      onPage(payload, { startMs: cursor, endMs: range.endMs });
      return;
    }
    const tail = payload.data.at(-1);
    // Older servers omit next_cursor. Their one-side page can only resume
    // immediately after the last observed minute.
    const next = payload.nextStartMs === undefined && tail
      ? tail.bucketStartMs + 60_000
      : payload.nextStartMs;
    if (!tail || tail.bucketStartMs < cursor || next == null
      || next <= tail.bucketStartMs || next > range.endMs) {
      throw new ApiPayloadError("liquidations.history.next_cursor", `${side} history did not advance its cursor`);
    }
    onPage(payload, { startMs: cursor, endMs: next - 1 });
    cursor = next;
  }
}
