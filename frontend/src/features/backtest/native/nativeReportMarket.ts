import type { MarketSymbolRef } from "../../symbol-search/venueContractLookup.js";
import type { NativeRun } from "./nativeBacktestApi.js";

/** The run's market; the Pine context symbol carries the exchange prefix ("BINANCE:XAUUSDT"). */
export function nativeReportMarket(run: Pick<NativeRun, "config">): MarketSymbolRef | null {
  const config = run.config;
  const symbol = config?.context?.symbol?.split(":").at(-1)?.trim() ?? "";
  return config?.exchange && config.market_type && symbol
    ? { exchange: config.exchange, marketType: config.market_type, symbol }
    : null;
}
