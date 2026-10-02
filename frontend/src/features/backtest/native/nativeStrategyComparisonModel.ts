import type { NativeRun } from "./nativeBacktestApi.js";

export function comparisonMetrics(run: NativeRun) {
  const equity = (run.result?.equity ?? []).filter((p) => Number.isFinite(p.time) && Number.isFinite(p.value)).slice().sort((a, b) => a.time - b.time);
  const baseline = equity[0]?.value;
  let peak = baseline ?? 0;
  const points = equity.map((p) => {
    peak = Math.max(peak, p.value);
    return { time: p.time, returnPct: baseline !== undefined && baseline > 0 ? (p.value / baseline - 1) * 100 : null,
      drawdownPct: peak > 0 ? (p.value / peak - 1) * 100 : null };
  });
  const profits = (run.result?.trades ?? []).map((trade) => trade.profit ?? trade.net_pnl);
  const completeProfits = run.execution_mode !== "CANDLESCOPE" && profits.length > 0 && profits.every((value) => typeof value === "number" && Number.isFinite(value));
  const returns = points.length > 1 ? points.at(-1)?.returnPct ?? null : null;
  const drawdowns = points.flatMap((p) => p.drawdownPct === null ? [] : [p.drawdownPct]);
  return { points, returns, maxDrawdown: points.length > 1 && drawdowns.length === points.length ? Math.abs(drawdowns.reduce((minimum, value) => Math.min(minimum, value), 0)) : null,
    trades: run.result?.trades.length ?? 0, winRate: completeProfits ? profits.filter((p) => typeof p === "number" && p > 0).length / profits.length * 100 : null };
}

/** Unknown metadata must never be interpreted as proof of equal test conditions. */
export function comparisonConditions(run: NativeRun): Record<string, string | null> {
  const config: Record<string, unknown> = run.config ?? {};
  const scalar = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : null;
  return {
    symbol: run.config?.context?.symbol ?? null,
    interval: run.config?.interval ?? run.config?.context?.timeframe ?? null,
    start: scalar(config.start_time_ms), end: scalar(config.end_time_ms), snapshot: scalar(config.snapshot_hash),
    engine: `${run.execution_mode ?? "NATIVE"} · ${run.runtime_identity.engine.package} · ${run.runtime_identity.engine.version}`,
    fill: run.result?.fill_model ?? null,
    initial: scalar(config.initial_balance ?? config.initial_capital),
    fees: scalar(config.taker_fee_bps ?? config.commission_value), slippage: scalar(config.slippage_bps ?? config.slippage),
  };
}

export function conditionStatus(values: Array<string | null>): "same" | "different" | "unknown" {
  const known = values.filter((v): v is string => v !== null);
  if (new Set(known).size > 1) return "different";
  return known.length === values.length && known.length > 1 ? "same" : "unknown";
}
