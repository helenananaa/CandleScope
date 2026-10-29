import type { MarketSeries, SeriesKey } from "../marketDataTypes.js";
import { asSeriesKey } from "../marketDataTypes.js";
import { canonicalizeIntervalValue } from "../../../utils/intervals.js";
import { isLegacyKlineSeriesIdentity, klineSeriesIdentityKey } from "../klineSeriesIdentity.js";

export function buildSeriesWindowKey(series: Partial<MarketSeries> = {}): SeriesKey {
  const {
    exchange = "binance",
    marketType = "spot",
    symbol = "",
    interval = "",
  } = series;
  const routed = [
    String(exchange || "binance").trim().toLowerCase(),
    String(marketType || "spot").trim().toLowerCase(),
    String(symbol || "").trim().toUpperCase(),
    canonicalizeIntervalValue(interval) || String(interval || "").trim(),
  ].join("-");
  return asSeriesKey(
    isLegacyKlineSeriesIdentity(exchange, series)
      ? routed
      : `${klineSeriesIdentityKey(exchange, series)}::${routed}`,
  );
}

