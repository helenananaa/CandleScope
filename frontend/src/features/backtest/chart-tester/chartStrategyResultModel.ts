import { getNumberLocale } from "../../../i18n/index.js";
import type { ExportScope } from "../../export/exportTypes.js";
import type { BacktestReport } from "../backtestTypes.js";

export const CHART_STRATEGY_TRADE_ROW_HEIGHT = 38;
export const CHART_STRATEGY_TRADE_OVERSCAN_ROWS = 6;

export interface VirtualTradeWindow {
  start: number;
  end: number;
  offsetTop: number;
  totalHeight: number;
}

export function chartStrategyVirtualTradeWindow({
  count,
  scrollTop,
  viewportHeight,
  rowHeight = CHART_STRATEGY_TRADE_ROW_HEIGHT,
  overscan = CHART_STRATEGY_TRADE_OVERSCAN_ROWS,
}: {
  count: number;
  scrollTop: number;
  viewportHeight: number;
  rowHeight?: number;
  overscan?: number;
}): VirtualTradeWindow {
  const safeCount = Math.max(0, Math.floor(count));
  const safeHeight = Math.max(1, rowHeight);
  const first = Math.max(0, Math.floor(Math.max(0, scrollTop) / safeHeight) - overscan);
  const visibleRows = Math.ceil(Math.max(0, viewportHeight) / safeHeight);
  const end = Math.min(safeCount, first + visibleRows + overscan * 2);
  return {
    start: Math.min(first, end),
    end,
    offsetTop: Math.min(first, end) * safeHeight,
    totalHeight: safeCount * safeHeight,
  };
}

export function chartStrategyMetricValue(value: unknown, fallback = "—"): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const metric = value as { value?: unknown; reason?: unknown };
    if (metric.value !== null && metric.value !== undefined) return String(metric.value);
    if (metric.reason) return fallback;
  }
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function chartStrategyWinRate(value: unknown, locale: string): string {
  const raw = chartStrategyMetricValue(value);
  if (raw === "—" || raw.endsWith("%")) return raw;
  const ratio = Number(raw);
  return Number.isFinite(ratio) && ratio >= 0 && ratio <= 1
    ? new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(ratio)
    : "—";
}

export function chartStrategyMaxDrawdown(report: BacktestReport): string {
  const risk = report.performance?.risk ?? {};
  const metric = risk.max_drawdown ?? risk.max_drawdown_percent ?? risk.maximum_drawdown;
  const raw = metric === undefined || metric === null
    ? sampledReportDrawdown(report)?.maximum
    : chartStrategyMetricValue(metric);
  if (raw === undefined || raw === "—") return "—";
  const value = Number(raw);
  if (!Number.isFinite(value)) return "—";
  return formatChartStrategyNumber(risk.max_drawdown_percent != null && risk.max_drawdown == null
    ? value / 100 : value, "percent");
}

/** Older reports have sampled event equity but no v2 performance block. */
export function sampledReportDrawdown(report: BacktestReport) {
  const points = report.equity_curve ?? [];
  if (points.length < 2) return null;
  const values = points.map((point) => ({
    equity: Number(point.equity), event_time_ms: Number(point.event_time_ms),
  })).sort((a, b) => a.event_time_ms - b.event_time_ms);
  if (values.some((point) => !Number.isFinite(point.equity) || !Number.isFinite(point.event_time_ms))) return null;
  const initial = Number(report.account?.initial_balance);
  let peak = Number.isFinite(initial) && initial > 0 ? Math.max(initial, values[0]!.equity) : values[0]!.equity;
  if (peak <= 0) return null;
  let maximum = 0;
  const curve = values.map((point) => {
    peak = Math.max(peak, point.equity);
    const drawdown = (point.equity - peak) / peak;
    maximum = Math.max(maximum, -drawdown);
    return { event_time_ms: point.event_time_ms, drawdown: String(drawdown) };
  });
  return { maximum, curve };
}

export function chartStrategyDrawdownDetailKey(report: BacktestReport) {
  const risk = report.performance?.risk ?? {};
  const metric = risk.max_drawdown ?? risk.max_drawdown_percent ?? risk.maximum_drawdown;
  if (metric == null && sampledReportDrawdown(report)) return "chartTester.result.drawdownBasis" as const;
  if (chartStrategyMetricValue(metric) !== "—") return "chartTester.result.drawdownBasis" as const;
  if (metric === null || metric === undefined) return "chartTester.result.drawdownMissing" as const;
  if (typeof metric === "object" && metric.reason === "INSUFFICIENT_EQUITY_SAMPLES") {
    return "chartTester.result.drawdownSamples" as const;
  }
  return "chartTester.result.drawdownUnavailable" as const;
}

export function chartStrategyTradeFocusTimeMs(trade: Record<string, unknown>): number | null {
  const value = Number(trade.entry_time_ms ?? trade.exit_time_ms);
  return Number.isFinite(value) ? value : null;
}

export function chartStrategyResultIncludedInExportScope(scope: ExportScope): boolean {
  return scope === "page";
}

export function formatChartStrategyNumber(value: unknown, kind: "amount" | "price" | "percent" = "amount"): string {
  const raw = chartStrategyMetricValue(value);
  const number = Number(raw);
  if (!Number.isFinite(number)) return raw;
  return new Intl.NumberFormat(getNumberLocale(), kind === "price"
    ? { maximumSignificantDigits: 8 }
    : kind === "percent"
      ? { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number);
}
