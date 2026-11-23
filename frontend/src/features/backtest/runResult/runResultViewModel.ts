import type { StrategyTradeFocus } from "../chart-tester/strategyTradeReview.js";
import type { RunResult, RunResultTrade } from "./runResult.js";

/** Where a trade sits on the chart: its bars when anchored, otherwise the engine's own times. */
export function runResultTradeFocus(trade: RunResultTrade): StrategyTradeFocus {
  const entry = trade.entry_bar_time_ms ?? trade.entry_time_ms;
  const exit = trade.exit_bar_time_ms ?? trade.exit_time_ms;
  const price = (value: string) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  return { id: trade.id, entryTimeMs: entry, exitTimeMs: exit >= entry ? exit : null,
    entryPrice: price(trade.entry_price), exitPrice: price(trade.exit_price) };
}

export function runResultWinRate(result: RunResult): number | null {
  const { trade_count: count, winning_trades: wins } = result.summary;
  return count > 0 ? wins / count : null;
}
