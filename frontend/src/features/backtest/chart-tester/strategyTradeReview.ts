export interface StrategyTradeFocus {
  id: string;
  entryTimeMs: number;
  exitTimeMs: number | null;
  entryPrice: number | null;
  exitPrice: number | null;
}

function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/** Native trades use seconds, host reports use milliseconds. Fills have no invented exit. */
export function strategyTradeFocus(row: Record<string, unknown>, id: string): StrategyTradeFocus | null {
  const seconds = finite(row.entryTime ?? row.entry_time ?? row.time);
  const entryTimeMs = finite(row.entry_time_ms ?? row.event_time_ms) ?? (seconds === null ? null : seconds * 1000);
  if (entryTimeMs === null) return null;
  const exitSeconds = finite(row.exitTime ?? row.exit_time);
  const exitTimeMs = finite(row.exit_time_ms) ?? (exitSeconds === null ? null : exitSeconds * 1000);
  return { id, entryTimeMs, exitTimeMs: exitTimeMs !== null && exitTimeMs >= entryTimeMs ? exitTimeMs : null,
    entryPrice: finite(row.entryPrice ?? row.entry_price ?? row.price), exitPrice: finite(row.exitPrice ?? row.exit_price) };
}

export function strategyTradeRange(trade: StrategyTradeFocus, intervalSeconds: number) {
  const from = trade.entryTimeMs / 1000;
  const to = (trade.exitTimeMs ?? trade.entryTimeMs) / 1000;
  const padding = Math.max(Math.max(1, intervalSeconds) * 8, (to - from) * 0.25);
  return { from: from - padding, to: to + padding };
}
