/**
 * Running a fixed run again with changed settings (ADR-BACKTEST-015 P5c): the same strategy and input,
 * with new parameters, fill accuracy, account, costs or risk limits.
 */
/** What a derived run may change; the backend keeps the same list (BacktestService.DERIVABLE_RUN_SETTINGS). */
export const DERIVABLE_RUN_SETTINGS = [
  "parameters", "fidelity_mode", "source_event_kind", "execution_data",
  "initial_balance", "equity_percent", "leverage", "sizing_policy", "fixed_qty", "fixed_notional",
  "taker_fee_bps", "maker_fee_bps", "slippage_bps", "fee_source", "funding_mode", "funding_rate",
  "latency_ms", "latency_events", "participation_rate", "order_end_policy", "cost_sensitivity_mode",
  "max_leverage", "max_notional", "max_abs_position_qty", "max_active_orders", "max_drawdown_percent",
  "daily_loss_limit", "max_cumulative_fees", "max_order_risk", "risk_per_stop_percent", "stop_distance",
] as const;
/** The run's changeable settings that it has, as served. */
export function derivableSettings(config: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(DERIVABLE_RUN_SETTINGS.filter((key) => config[key] !== null && config[key] !== undefined)
    .map((key) => [key, config[key]]));
}

/** The settings that differ from the run's own; null when the text is not a JSON object. */
export function changedSettings(original: Record<string, unknown>, text: string): Record<string, unknown> | null {
  let edited: unknown;
  try { edited = JSON.parse(text); } catch { return null; }
  if (edited === null || typeof edited !== "object" || Array.isArray(edited)) return null;
  return Object.fromEntries(Object.entries(edited).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key])));
}
