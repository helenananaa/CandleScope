import type { TradingChartContext } from "./tradingTypes.js";

/**
 * The market fields of a practice order or manual fill placed from a chart.
 * A chart on a provider series (Twelve Data's AAPL:NASDAQ, say) also sends its
 * `identity`, so the account matches and values the bars the chart shows
 * (ADR-DATA-002 D1c); the exchange's own series sends none.
 */
export function chartInstrumentFields(context: TradingChartContext): Record<string, unknown> {
  return {
    exchange: context.exchange,
    marketType: context.marketType,
    symbol: context.symbol,
    ...(context.identity ? { identity: context.identity } : {}),
  };
}
