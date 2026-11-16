import { translateExchangeName, translateMarketType } from "../../i18n/index.js";

const INTERVAL = /^\d+[smhdwM]$/;

/**
 * A cache entry's key as a person reads it. Series keys look like `2\u0000binance-spot-BTCUSDT-1m` or
 * `chart:1:binance-spot-BTCUSDT-1h` (an owner prefix, then exchange, market, symbol and interval); they read "Binance · 现货 · BTCUSDT · 1m".
 * Any other key is shown as it is, with separators made visible.
 */
export function cacheEntryLabel(key: string | null | undefined): string {
  if (!key) return "—";
  // The series is the last part after an owner prefix ("2\u0000…" or "chart:1:…").
  const series = key.slice(Math.max(key.lastIndexOf("\u0000"), key.lastIndexOf(":")) + 1);
  const parts = series.split("-");
  const interval = parts.at(-1) ?? "";
  if (parts.length >= 4 && INTERVAL.test(interval)) {
    const [exchange = "", market = ""] = parts;
    const symbol = parts.slice(2, -1).join("-");
    return [translateExchangeName(exchange), translateMarketType(market), symbol, interval].join(" · ");
  }
  return key.replaceAll("\u0000", " · ");
}
