import type { TradeFlowConnectionStatus } from "./tradeFlowTypes.js";

/** Absence of trades is observable; it is not proof of a broken connection. */
export function isTradeFlowQuiet(status: TradeFlowConnectionStatus, lastTradeTime: number | null, now: number): boolean {
  return status === "live" && lastTradeTime !== null && now - lastTradeTime >= 60_000;
}

export function latestTradeTime(records: readonly { tradeTimeMs: number }[]): number | null {
  return records.reduce<number | null>((latest, trade) => (
    latest === null ? trade.tradeTimeMs : Math.max(latest, trade.tradeTimeMs)
  ), null);
}
