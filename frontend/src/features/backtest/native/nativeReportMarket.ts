import type { MarketSymbolRef } from "../../symbol-search/venueContractLookup.js";
import type { NativeRun } from "./nativeBacktestApi.js";

/**
 * The run's market; the Pine context symbol carries the exchange prefix ("BINANCE:XAUUSDT"),
 * and only the first ":" ends it ("TWELVEDATA:AAPL:NASDAQ").
 */
export function nativeReportMarket(run: Pick<NativeRun, "config">): MarketSymbolRef | null {
  const config = run.config;
  const tickerId = config?.context?.symbol ?? "";
  const separator = tickerId.indexOf(":");
  const symbol = (separator < 0 ? tickerId : tickerId.slice(separator + 1)).trim();
  return config?.exchange && config.market_type && symbol
    ? { exchange: config.exchange, marketType: config.market_type, symbol }
    : null;
}
