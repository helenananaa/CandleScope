import { strategyTradeFocus } from "../chart-tester/strategyTradeReview.js";
import type { NativeResult } from "./nativeBacktestApi.js";

export function reportNumber(value: unknown): number | null {
  if (value == null || value === "" || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function reportTrade(row: Record<string, unknown>, orders: Record<string, unknown>[] = []) {
  const focus = strategyTradeFocus(row, "report");
  const profit = reportNumber(row.profit ?? row.net_pnl);
  // Match actual engine entry orders, never infer direction from an order ID
  // such as "L", price movement or profit sign. Ambiguity remains unavailable.
  const entries = orders.filter(order => row.id != null && order.id === row.id
    && reportNumber(order.time) === reportNumber(row.entryTime)
    && reportNumber(order.price) === reportNumber(row.entryPrice)
    && reportNumber(order.qty) === reportNumber(row.qty)
    && ["strategy.long", "strategy.short"].includes(String(order.direction)));
  const entry = entries.length === 1 ? entries[0] : undefined;
  const direction = String(row.direction ?? row.side ?? entry?.direction ?? "").toLowerCase();
  const side = ["long", "buy", "strategy.long"].includes(direction) ? "long"
    : ["short", "sell", "strategy.short"].includes(direction) ? "short" : null;
  const quantity = reportNumber(row.qty ?? row.quantity);
  const engineReturn = reportNumber(row.profit_percent ?? row.return_percent);
  const price = reportNumber(row.entryPrice);
  const notionalReturn = entry && profit != null && price != null && price > 0 && quantity != null && quantity !== 0
    ? profit / (price * Math.abs(quantity)) * 100 : null;
  return { focus, profit, side, quantity, derivedReturn: engineReturn == null && notionalReturn != null,
    duration: focus?.exitTimeMs != null ? focus.exitTimeMs - focus.entryTimeMs : null,
    returnPercent: engineReturn ?? notionalReturn };
}

export function reportAnalytics(result: NativeResult, external = false) {
  const equity = result.equity.filter(p => Number.isFinite(p.time) && Number.isFinite(p.value)).slice().sort((a, b) => a.time - b.time);
  const baseline = equity[0]?.value ?? null;
  let peak = baseline ?? 0;
  let maxDrawdown = 0;
  let maxDrawdownPercent = 0;
  const series = equity.map(point => {
    peak = Math.max(peak, point.value);
    const drawdown = peak - point.value;
    const drawdownPercent = peak > 0 ? drawdown / peak * 100 : null;
    maxDrawdown = Math.max(maxDrawdown, drawdown);
    maxDrawdownPercent = Math.max(maxDrawdownPercent, drawdownPercent ?? 0);
    return { ...point, returnPercent: baseline != null && baseline > 0 ? (point.value / baseline - 1) * 100 : null, drawdownPercent };
  });
  const closed = external ? [] : result.trades.map(row => reportTrade(row, result.orders)).filter(trade => trade.focus?.exitTimeMs != null);
  const complete = closed.length > 0 && closed.every(trade => trade.profit != null);
  const wins = closed.filter(trade => (trade.profit ?? 0) > 0).length;
  const grossProfit = closed.reduce((sum, trade) => sum + Math.max(0, trade.profit ?? 0), 0);
  const grossLoss = closed.reduce((sum, trade) => sum + Math.max(0, -(trade.profit ?? 0)), 0);
  const bars = result.bars.filter(bar => Number.isFinite(bar.time) && Number.isFinite(bar.close) && bar.time >= (equity[0]?.time ?? Infinity) && bar.time <= (equity.at(-1)?.time ?? -Infinity)).slice().sort((a, b) => a.time - b.time);
  const firstPrice = bars[0]?.close;
  const benchmark = firstPrice != null && firstPrice > 0 ? bars.map(bar => ({ time: bar.time, value: (bar.close / firstPrice - 1) * 100 })) : [];
  return { equity, series, baseline, benchmark, closedCount: closed.length, wins,
    equityChange: equity.length >= 2 ? equity.at(-1)!.value - equity[0]!.value : null,
    maxDrawdown: equity.length >= 2 ? maxDrawdown : null,
    maxDrawdownPercent: equity.length >= 2 && baseline != null && baseline > 0 ? maxDrawdownPercent : null,
    netProfit: complete ? grossProfit - grossLoss : null,
    winRate: complete ? wins / closed.length * 100 : null,
    profitFactor: complete && grossLoss > 0 ? grossProfit / grossLoss : complete && grossProfit > 0 ? Infinity : null };
}

export function formatReportPercent(value: number | null, locale: string): string {
  if (value == null) return "—";
  if (value !== 0 && Math.abs(value) < 0.01) return `${value < 0 ? ">−" : "<"}${(0.01).toLocaleString(locale)}%`;
  return `${value.toLocaleString(locale, { maximumFractionDigits: 2 })}%`;
}
