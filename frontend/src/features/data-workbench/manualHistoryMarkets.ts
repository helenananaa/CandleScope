import type { ExchangeCatalog } from "../chart-session/chartSessionTypes.js";

export function manualHistoryMarkets(catalog: ExchangeCatalog, exchange: string) {
  const entry = catalog[exchange];
  return entry?.markets.filter((market) => entry.raw?.channels?.some((channel) => (
    channel.channel === "kline" && channel.history && channel.market_types.includes(market.market_type)
  ))) || [];
}

export function manualHistoryExchanges(catalog: ExchangeCatalog) {
  return Object.values(catalog).filter((entry) => manualHistoryMarkets(catalog, entry.id).length > 0);
}
